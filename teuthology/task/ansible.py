import json
import logging
import re
import requests
import os
import pathlib
import pexpect
import yaml
import shutil

from tempfile import mkdtemp, NamedTemporaryFile

from teuthology import repo_utils
from teuthology.config import config as teuth_config
from teuthology.exceptions import CommandFailedError, AnsibleFailedError
from teuthology.job_status import set_status
from teuthology.task import Task
from teuthology.util.loggerfile import LoggerFile

log = logging.getLogger(__name__)


class FailureAnalyzer:
    def analyze(self, failure_log):
        failure_obj = yaml.safe_load(failure_log)
        lines = set()
        if failure_obj is None:
            return lines
        for host_obj in failure_obj.values():
            if not isinstance(host_obj, dict):
                continue
            lines = lines.union(self.analyze_host_record(host_obj))
        return sorted(lines)

    def analyze_host_record(self, record):
        lines = set()
        for result in record.get("results", [record]):
            cmd = result.get("cmd", "")
            # When a CPAN task fails, we get _lots_ of stderr_lines, and they
            # aren't practical to reduce meaningfully. Instead of analyzing lines,
            # just report the command that failed.
            if "cpan" in cmd:
                lines.add(f"CPAN command failed: {cmd}")
                continue
            lines_to_analyze = []
            if "stderr_lines" in result:
                lines_to_analyze = result["stderr_lines"]
            elif "msg" in result:
                lines_to_analyze = result["msg"].split("\n")
            lines_to_analyze.extend(result.get("err", "").split("\n"))
            for line in lines_to_analyze:
                line = self.analyze_line(line.strip())
                if line:
                    lines.add(line)
        return list(lines)

    def analyze_line(self, line):
        if line.startswith("W: ") or line.endswith("?"):
            return ""
        drop_phrases = [
            # apt output sometimes contains warnings or suggestions. Those won't be
            # helpful, so throw them out.
            r"^W: ",
            r"\?$",
            # some output from SSH is not useful
            r"Warning: Permanently added .+ to the list of known hosts.",
            r"^@+$",
        ]
        for phrase in drop_phrases:
            match = re.search(rf"({phrase})", line, flags=re.IGNORECASE)
            if match:
                return ""

        # Next, we can normalize some common phrases.
        phrases = [
            "connection timed out",
            r"(unable to|could not) connect to [^ ]+",
            r"temporary failure resolving [^ ]+",
            r"Permissions \d+ for '.+' are too open.",
        ]
        for phrase in phrases:
            match = re.search(rf"({phrase})", line, flags=re.IGNORECASE)
            if match:
                line = match.groups()[0]
                break

        # Strip out URLs for specific packages
        package_re = re.compile(r"https?://.*\.(deb|rpm)")
        line = package_re.sub("<package>", line)
        # Strip out IP addresses
        ip_re = re.compile(r"\[IP: \d+\.\d+\.\d+\.\d+( \d+)?\]")
        line = ip_re.sub("", line)
        return line


class Ansible(Task):
    """
    A task to run ansible playbooks

    Required configuration parameters:
        playbook:   Required; can either be a list of plays, or a path/URL to a
                    playbook. In the case of a path, it may be relative to the
                    repo's on-disk location (if a repo is provided), or
                    teuthology's working directory.

    Optional configuration parameters:
        repo:       A path or URL to a repo (defaults to '.'). Given a repo
                    value of 'foo', ANSIBLE_ROLES_PATH is set to 'foo/roles'
        branch:     If pointing to a remote git repo, use this branch. Defaults
                    to 'main'.
        hosts:      A list of teuthology roles or partial hostnames (or a
                    combination of the two). ansible-playbook will only be run
                    against hosts that match.
        inventory:  A path to be passed to ansible-playbook with the
                    --inventory-file flag; useful for playbooks that also have
                    vars they need access to. If this is not set, we check for
                    /etc/ansible/hosts and use that if it exists. If it does
                    not, we generate a temporary file to use.
        tags:       A string including any (comma-separated) tags to be passed
                    directly to ansible-playbook.
        skip_tags:  A string of comma-separated tags that will be skipped by 
                    passing them to ansible-playbook using --skip-tags.
        vars:       A dict of vars to be passed to ansible-playbook via the
                    --extra-vars flag
        group_vars: A dict with keys matching relevant group names in the
                    playbook, and values to be written in the corresponding
                    inventory's group_vars files. Only applies to inventories
                    generated by this task.
        cleanup:    If present, the given or generated playbook will be run
                    again during teardown with a 'cleanup' var set to True.
                    This will allow the playbook to clean up after itself,
                    if the playbook supports this feature.
        reconnect:  If set to True (the default), then reconnect to hosts after
                    ansible-playbook completes. This is in case the playbook
                    makes changes to the SSH configuration, or user accounts -
                    we would want to reflect those changes immediately.

    Examples:

    tasks:
    - ansible:
        repo: https://github.com/ceph/ceph-cm-ansible.git
        playbook:
          - roles:
            - some_role
            - another_role
        hosts:
          - client.0
          - host1

    tasks:
    - ansible:
        repo: /path/to/repo
        inventory: /path/to/inventory
        playbook: /path/to/playbook.yml
        tags: my_tags
        skip_tags: my_skipped_tags
        vars:
            var1: string_value
            var2:
                - list_item
            var3:
                key: value

    """
    # set this in subclasses to provide a group to
    # assign hosts to for dynamic inventory creation
    inventory_group = None

    def __init__(self, ctx, config):
        super(Ansible, self).__init__(ctx, config)
        self.generated_inventory = False
        self.generated_playbook = False
        self.log = logging.Logger(__name__)
        if ctx.archive:
            self.log.addHandler(logging.FileHandler(
                os.path.join(ctx.archive, "ansible.log")))

    def setup(self):
        super(Ansible, self).setup()
        self.find_repo()
        self.get_playbook()
        self.get_inventory() or self.generate_inventory()
        if not hasattr(self, 'playbook_file'):
            self.generate_playbook()

    @property
    def failure_log(self):
        if not hasattr(self, '_failure_log'):
            self._failure_log = NamedTemporaryFile(
                prefix="teuth_ansible_failures_",
                delete=False,
            )
        return self._failure_log

    def find_repo(self):
        """
        Locate the repo we're using; cloning it from a remote repo if necessary
        """
        repo = self.config.get('repo', '.')
        if repo.startswith(('http://', 'https://', 'git@', 'git://')):
            repo_path = repo_utils.fetch_repo(
                repo,
                self.config.get('branch', 'main'),
            )
        else:
            repo_path = os.path.abspath(os.path.expanduser(repo))
        self.repo_path = repo_path

    def get_playbook(self):
        """
        If necessary, fetch and read the playbook file
        """
        playbook = self.config['playbook']
        if isinstance(playbook, list):
            # Multiple plays in a list
            self.playbook = playbook
        elif isinstance(playbook, str) and playbook.startswith(('http://',
                                                               'https://')):
            response = requests.get(playbook)
            response.raise_for_status()
            self.playbook = yaml.safe_load(response.text)
        elif isinstance(playbook, str):
            try:
                playbook_path = os.path.expanduser(playbook)
                if not playbook_path.startswith('/'):
                    # If the path is not absolute at this point, look for the
                    # playbook in the repo dir. If it's not there, we assume
                    # the path is relative to the working directory
                    pb_in_repo = os.path.join(self.repo_path, playbook_path)
                    if os.path.exists(pb_in_repo):
                        playbook_path = pb_in_repo
                self.playbook_file = open(playbook_path)
                playbook_yaml = yaml.safe_load(self.playbook_file)
                self.playbook = playbook_yaml
            except Exception:
                log.error("Unable to read playbook file %s", playbook)
                raise
        else:
            raise TypeError(
                "playbook value must either be a list, URL or a filename")
        log.info("Playbook: %s", self.playbook)

    def get_inventory(self):
        """
        Determine whether or not we're using an existing inventory file
        """
        self.inventory = self.config.get('inventory')
        etc_ansible_hosts = '/etc/ansible/hosts'
        if self.inventory:
            self.inventory = os.path.expanduser(self.inventory)
        elif os.path.exists(etc_ansible_hosts):
            self.inventory = etc_ansible_hosts
        return self.inventory

    def generate_inventory(self):
        """
        Generate a hosts (inventory) file to use. This should not be called if
        we're using an existing file.
        """
        hosts = self.cluster.remotes.keys()
        hostnames = []
        proxy = []
        for remote in hosts:
            if teuth_config.tunnel:
                for tunnel in teuth_config.tunnel:
                    cmd = None
                    if remote.hostname in tunnel.get('hosts'):
                        bastion = tunnel.get('bastion')
                        if not bastion:
                            log.error("The 'tunnel' config must include 'bastion' entry")
                            continue
                        host = bastion.get('host', None)
                        if not host:
                            log.error("Bastion host is not provided. Tunnel ignored.")
                            continue
                        user = bastion.get('user', None)
                        word = bastion.get('word', None)
                        port = bastion.get('port', 22)
                        pkey = bastion.get('identity', None)
                        opts = "-W %h:%p"
                        if word:
                            log.warning(f"Password authentication requested for the bastion '{host}' "
                                        f"in order to connect to remote '{remote.hostname}'. "
                                        f"The password authentication is not supported and will be ignored")
                        if port:
                            opts += f" -p {port}"
                        if pkey:
                            opts += f" -i {pkey}"
                        if user:
                            opts += f" {user}@{host}"
                        else:
                            opts += f" {host}"
                        cmd = f"ssh {opts}"
                        if not host in proxy:
                            proxy.append(host)
                        break
                if cmd:
                    i = f"{remote.hostname} ansible_ssh_common_args='-o ProxyCommand=\"{cmd}\" -o StrictHostKeyChecking=no'"
                else:
                    i = remote.hostname
            else:
                i = remote.hostname
            hostnames.append(i)
        inventory = []
        if self.inventory_group:
            inventory.append('[{0}]'.format(self.inventory_group))

        inventory.extend(sorted(hostnames) + [''])

        if len(proxy) > 0:
            inventory.append('[proxy]')
            inventory.extend(sorted(proxy) + [''])

        hosts_str = '\n'.join(inventory)

        self.inventory = self._write_inventory_files(hosts_str)
        self.generated_inventory = True

    def _write_inventory_files(self, inventory, inv_suffix=''):
        """
        Actually write the inventory files. Writes out group_vars files as
        necessary based on configuration.

        :param inventory:  The content of the inventory file itself, as a
                           string
        :param inv_suffix: The suffix to use for the inventory filename
        """
        # First, create the inventory directory
        inventory_dir = mkdtemp(
            prefix="teuth_ansible_inventory",
        )
        inv_fn = os.path.join(inventory_dir, 'inventory')
        if inv_suffix:
            inv_fn = '.'.join(inv_fn, inv_suffix)
        # Write out the inventory file
        inv_file = open(inv_fn, 'w')
        inv_file.write(inventory)
        # Next, write the group_vars files
        all_group_vars = self.config.get('group_vars')
        if all_group_vars:
            group_vars_dir = os.path.join(inventory_dir, 'group_vars')
            os.mkdir(group_vars_dir)
            # We loop over a sorted list of keys here because we want our tests
            # to be able to mock predictably
            for group_name in sorted(all_group_vars):
                group_vars = all_group_vars[group_name]
                path = os.path.join(group_vars_dir, group_name + '.yml')
                gv_file = open(path, 'w')
                yaml.safe_dump(group_vars, gv_file)

        return inventory_dir

    def generate_playbook(self):
        """
        Generate a playbook file to use. This should not be called if we're
        using an existing file.
        """
        playbook_file = NamedTemporaryFile(
            prefix="teuth_ansible_playbook_",
            dir=self.repo_path,
            delete=False,
        )
        yaml.safe_dump(self.playbook, playbook_file, explicit_start=True)
        playbook_file.flush()
        self.playbook_file = playbook_file
        self.generated_playbook = True

    def begin(self):
        super(Ansible, self).begin()
        if len(self.cluster.remotes) > 0:
            self.execute_playbook()
        else:
            log.info("There are no remotes; skipping playbook execution")

    def execute_playbook(self, _logfile=None):
        """
        Execute ansible-playbook

        :param _logfile: Use this file-like object instead of a LoggerFile for
                         testing
        """
        environ = os.environ
        environ['ANSIBLE_SSH_PIPELINING'] = '1'
        environ['ANSIBLE_FAILURE_LOG'] = self.failure_log.name
        environ['ANSIBLE_ROLES_PATH'] = "%s/roles" % self.repo_path
        environ['ANSIBLE_NOCOLOR'] = "1"
        # Store collections in <repo root>/.ansible/
        # This is the same path used in <repo root>/ansible.cfg
        environ['ANSIBLE_COLLECTIONS_PATH'] = str(
            pathlib.Path(__file__).parents[2] / ".ansible")
        args = self._build_args()
        command = ' '.join(args)
        log.debug("Running %s", command)

        out, status = pexpect.run(
            command,
            cwd=self.repo_path,
            logfile=_logfile or LoggerFile(self.log, logging.INFO),
            withexitstatus=True,
            timeout=None,
        )
        if status != 0:
            self._handle_failure(command, status)

        if self.config.get('reconnect', True) is True:
            remotes = list(self.cluster.remotes)
            log.debug("Reconnecting to %s", remotes)
            for remote in remotes:
                remote.reconnect()

    def _handle_failure(self, command, status):
        self._set_status('dead')
        failures = None
        with open(self.failure_log.name, 'r') as fail_log_file:
            fail_log = fail_log_file.read()
            try:
                analyzer = FailureAnalyzer()
                failures = analyzer.analyze(fail_log)
            except yaml.YAMLError as e:
                log.error(
                    f"Failed to parse ansible failure log: {self.failure_log.name} ({e})"
                )
            except Exception:
                log.exception(f"Failed to analyze ansible failure log: {self.failure_log.name}")
            # If we hit an exception, or if analyze() returned nothing, use the log as-is
            if not failures:
                failures = fail_log.replace('\n', '')

        if failures:
            self._archive_failures()
            raise AnsibleFailedError(failures)
        raise CommandFailedError(command, status)

    def _set_status(self, status):
        """
        Not implemented in the base class
        """
        pass

    def _archive_failures(self):
        if self.ctx.archive:
            archive_path = "{0}/ansible_failures.yaml".format(self.ctx.archive)
            log.info("Archiving ansible failure log at: {0}".format(
                archive_path,
            ))
            shutil.move(
                self.failure_log.name,
                archive_path
            )
            os.chmod(archive_path, 0o664)

    def _build_args(self):
        """
        Assemble the list of args to be executed
        """
        fqdns = [r.hostname for r in self.cluster.remotes.keys()]
        # Assume all remotes use the same username
        user = list(self.cluster.remotes)[0].user
        extra_vars = dict(ansible_ssh_user=user)
        extra_vars.update(self.config.get('vars', dict()))
        args = [
            'ansible-playbook', '-v',
            "--extra-vars", "'%s'" % json.dumps(extra_vars),
            '-i', self.inventory,
            '--limit', ','.join(fqdns),
            self.playbook_file.name,
        ]
        tags = self.config.get('tags')
        if tags:
            args.extend(['--tags', tags])
        skip_tags = self.config.get('skip_tags')
        if skip_tags:
            args.extend(['--skip-tags', skip_tags])
        return args

    def teardown(self):
        self._cleanup()
        if self.generated_inventory:
            shutil.rmtree(self.inventory)
        if self.generated_playbook:
            os.remove(self.playbook_file.name)
        super(Ansible, self).teardown()

    def _cleanup(self):
        """
        If the ``cleanup`` key exists in config the same playbook will be
        run again during the teardown step with the var ``cleanup`` given with
        a value of ``True``.  If supported, this will allow the playbook to
        cleanup after itself during teardown.
        """
        if self.config.get("cleanup"):
            log.info("Running ansible cleanup...")
            extra = dict(cleanup=True)
            if self.config.get('vars'):
                self.config.get('vars').update(extra)
            else:
                self.config['vars'] = extra
            self.execute_playbook()
        else:
            log.info("Skipping ansible cleanup...")


class CephLab(Ansible):
    __doc__ = """
    A very simple subclass of Ansible that defaults to:

    - ansible.cephlab:
        repo: {git_base}ceph-cm-ansible.git
        branch: main
        playbook: cephlab.yml

    If a dynamic inventory is used, all hosts will be assigned to the
    group 'testnodes'.
    """.format(git_base=teuth_config.ceph_git_base_url)

    # Set the name so that Task knows to look up overrides for
    # 'ansible.cephlab' instead of just 'cephlab'
    name = 'ansible.cephlab'
    inventory_group = 'testnodes'

    def __init__(self, ctx, config):
        config = config or dict()
        if 'playbook' not in config:
            config['playbook'] = 'cephlab.yml'
        if 'repo' not in config:
            config['repo'] = teuth_config.get_ceph_cm_ansible_git_url()
        super(CephLab, self).__init__(ctx, config)

    def begin(self):
        # Write foo to ~/.vault_pass.txt if it's missing.
        # In almost all cases we don't need the actual vault password.
        # Touching an empty file broke as of Ansible 2.4
        vault_pass_path = os.path.expanduser('~/.vault_pass.txt')
        if not os.path.exists(vault_pass_path):
            with open(vault_pass_path, 'w') as f:
                f.write('foo')
        super(CephLab, self).begin()

    def _set_status(self, status):
        set_status(self.ctx.summary, status)


task = Ansible
cephlab = CephLab
