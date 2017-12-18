import json
import os
import re
import logging
import yaml

from cStringIO import StringIO

from . import Task
from tempfile import NamedTemporaryFile
from ..config import config as teuth_config
from ..misc import get_scratch_devices
from teuthology import contextutil
from teuthology.orchestra import run
from teuthology import misc
log = logging.getLogger(__name__)


class CephAnsible(Task):
    name = 'ceph_ansible'

    __doc__ = """
    A task to setup ceph cluster using ceph-ansible

    - ceph-ansible:
        repo: {git_base}ceph-ansible.git
        branch: mybranch # defaults to master
        ansible-version: 2.2 # defaults to 2.2.1
        vars:
          ceph_dev: True ( default)
          ceph_conf_overrides:
             global:
                mon pg warn min per osd: 2

    It always uses a dynamic inventory.

    It will optionally do the following automatically based on ``vars`` that
    are passed in:
        * Set ``devices`` for each host if ``osd_auto_discovery`` is not True
        * Set ``monitor_interface`` for each host if ``monitor_interface`` is
          unset
        * Set ``public_network`` for each host if ``public_network`` is unset
    """.format(git_base=teuth_config.ceph_git_base_url)

    groups_to_roles = dict(
        mons='mon',
        mgrs='mgr',
        mdss='mds',
        osds='osd',
        rgws='rgw',
        clients='client',
    )

    def __init__(self, ctx, config):
        super(CephAnsible, self).__init__(ctx, config)
        config = self.config or dict()
        self.playbook = None
        if 'playbook' in config:
            self.playbook = self.config['playbook']
        if 'repo' not in config:
            self.config['repo'] = os.path.join(teuth_config.ceph_git_base_url,
                                               'ceph-ansible.git')
        # default vars to dev builds
        if 'vars' not in config:
            vars = dict()
            config['vars'] = vars
        vars = config['vars']
        if 'ceph_dev' not in vars:
            vars['ceph_dev'] = True
        if 'ceph_dev_key' not in vars:
            vars['ceph_dev_key'] = 'https://download.ceph.com/keys/autobuild.asc'
        if 'ceph_dev_branch' not in vars:
            vars['ceph_dev_branch'] = ctx.config.get('branch', 'master')
        self.cluster_name = vars.get('cluster', 'ceph')

    def setup(self):
        super(CephAnsible, self).setup()
        # generate hosts file based on test config
        self.generate_hosts_file()
        # generate playbook file if it exists in config
        self.playbook_file = None
        if self.playbook is not None:
            pb_buffer = StringIO()
            pb_buffer.write('---\n')
            yaml.safe_dump(self.playbook, pb_buffer)
            pb_buffer.seek(0)
            playbook_file = NamedTemporaryFile(
               prefix="ceph_ansible_playbook_", dir='/tmp/',
               delete=False,
            )
            playbook_file.write(pb_buffer.read())
            playbook_file.flush()
            self.playbook_file = playbook_file.name
        # everything from vars in config go into group_vars/all file
        extra_vars = dict()
        extra_vars.update(self.config.get('vars', dict()))
        gvar = yaml.dump(extra_vars, default_flow_style=False)
        self.extra_vars_file = self._write_hosts_file(prefix='teuth_ansible_gvar',
                                                      content=gvar)

    def execute_playbook(self):
        """
        Execute ansible-playbook

        :param _logfile: Use this file-like object instead of a LoggerFile for
                         testing
        """

        args = [
            'ANSIBLE_STDOUT_CALLBACK=debug',
            'ansible-playbook', '-vv',
            '-i', 'inven.yml', 'site.yml'
        ]
        log.debug("Running %s", args)
        # use the first mon node as installer node
        (ceph_installer,) = self.ctx.cluster.only(
            misc.get_first_mon(self.ctx,
                               self.config)).remotes.iterkeys()
        self.ceph_installer = ceph_installer
        self.args = args
        if self.config.get('rhbuild'):
            self.run_rh_playbook()
        else:
            self.run_playbook()

    def generate_hosts_file(self):
        hosts_dict = dict()
        for group in sorted(self.groups_to_roles.keys()):
            role_prefix = self.groups_to_roles[group]
            want = lambda role: role.startswith(role_prefix)
            for (remote, roles) in self.cluster.only(want).remotes.iteritems():
                hostname = remote.hostname
                host_vars = self.get_host_vars(remote)
                if group not in hosts_dict:
                    hosts_dict[group] = {hostname: host_vars}
                elif hostname not in hosts_dict[group]:
                    hosts_dict[group][hostname] = host_vars

        hosts_stringio = StringIO()
        for group in sorted(hosts_dict.keys()):
            hosts_stringio.write('[%s]\n' % group)
            for hostname in sorted(hosts_dict[group].keys()):
                vars = hosts_dict[group][hostname]
                if vars:
                    vars_list = []
                    for key in sorted(vars.keys()):
                        vars_list.append(
                            "%s='%s'" % (key, json.dumps(vars[key]).strip('"'))
                        )
                    host_line = "{hostname} {vars}".format(
                        hostname=hostname,
                        vars=' '.join(vars_list),
                    )
                else:
                    host_line = hostname
                hosts_stringio.write('%s\n' % host_line)
            hosts_stringio.write('\n')
        hosts_stringio.seek(0)
        self.inventory = self._write_hosts_file(prefix='teuth_ansible_hosts_',
                                                content=hosts_stringio.read().strip())
        self.generated_inventory = True

    def begin(self):
        super(CephAnsible, self).begin()
        self.execute_playbook()

    def _write_hosts_file(self, prefix, content):
        """
        Actually write the hosts file
        """
        hosts_file = NamedTemporaryFile(prefix=prefix,
                                        delete=False)
        hosts_file.write(content)
        hosts_file.flush()
        return hosts_file.name

    def teardown(self):
        log.info("Cleaning up temporary files")
        os.remove(self.inventory)
        if self.playbook is not None:
            os.remove(self.playbook_file)
        os.remove(self.extra_vars_file)
        # collect logs
        self.collect_logs()
        # run purge-cluster that teardowns the cluster
        args = [
            'ANSIBLE_STDOUT_CALLBACK=debug',
            'ansible-playbook', '-vv',
            '-e', 'ireallymeanit=yes',
            '-i', 'inven.yml', 'purge-cluster.yml'
        ]
        log.debug("Running %s", args)
        str_args = ' '.join(args)
        installer_node = self.ceph_installer
        # copy purge-cluster playbook from infra dir to top level dir
        # as required by ceph-ansible
        installer_node.run(
            args=[
                'cp',
                run.Raw('~/ceph-ansible/infrastructure-playbooks/purge-cluster.yml'),
                run.Raw('~/ceph-ansible/'),
            ]
        )
        if self.config.get('rhbuild'):
            installer_node.run(
                args=[
                    run.Raw('cd ~/ceph-ansible'),
                    run.Raw(';'),
                    run.Raw(str_args)
                ]
            )
        else:
            installer_node.run(
                args=[
                    run.Raw('cd ~/ceph-ansible'),
                    run.Raw(';'),
                    run.Raw('source venv/bin/activate'),
                    run.Raw(';'),
                    run.Raw(str_args)
                ]
            )
            # cleanup the ansible ppa repository we added
            # and also remove the dependency pkgs we installed
            if installer_node.os.package_type == 'deb':
                    installer_node.run(args=[
                        'sudo',
                        'add-apt-repository',
                        '--remove',
                        run.Raw('ppa:ansible/ansible'),
                    ])
                    installer_node.run(args=[
                        'sudo',
                        'apt-get',
                        'update',
                    ])
                    installer_node.run(args=[
                        'sudo',
                        'apt-get',
                        'remove',
                        '-y',
                        'ansible',
                        'libssl-dev',
                        'libffi-dev',
                        'python-dev'
                    ])
            else:
                # cleanup rpm packages the task installed
                installer_node.run(args=[
                    'sudo',
                    'yum',
                    'remove',
                    '-y',
                    'libffi-devel',
                    'python-devel',
                    'openssl-devel',
                    'libselinux-python'
                ])

    def collect_logs(self):
        ctx = self.ctx
        if ctx.archive is not None and \
                not (ctx.config.get('archive-on-error') and ctx.summary['success']):
            log.info('Archiving logs...')
            path = os.path.join(ctx.archive, 'remote')
            os.makedirs(path)

            def wanted(role):
                # Only attempt to collect logs from hosts which are part of the
                # cluster
                return any(map(
                    lambda role_stub: role.startswith(role_stub),
                    self.groups_to_roles.values(),
                ))
            for remote in ctx.cluster.only(wanted).remotes.keys():
                sub = os.path.join(path, remote.shortname)
                os.makedirs(sub)
                misc.pull_directory(remote, '/var/log/ceph',
                                    os.path.join(sub, 'log'))

    def wait_for_ceph_health(self):
        with contextutil.safe_while(sleep=15, tries=6,
                                    action='check health') as proceed:
            (remote,) = self.ctx.cluster.only('mon.a').remotes
            remote.run(args=[
                'sudo', 'ceph', '--cluster', self.cluster_name, 'osd', 'tree'
            ])
            remote.run(args=[
                'sudo', 'ceph', '--cluster', self.cluster_name, '-s'
            ])
            log.info("Waiting for Ceph health to reach HEALTH_OK \
                        or HEALTH WARN")
            while proceed():
                out = StringIO()
                remote.run(
                    args=['sudo', 'ceph', '--cluster', self.cluster_name,
                          'health'], 
                    stdout=out,
                )
                out = out.getvalue().split(None, 1)[0]
                log.info("cluster in state: %s", out)
                if out in ('HEALTH_OK', 'HEALTH_WARN'):
                    break

    def get_host_vars(self, remote):
        extra_vars = self.config.get('vars', dict())
        host_vars = dict()
        if not extra_vars.get('osd_auto_discovery', False):
            roles = self.ctx.cluster.remotes[remote]
            dev_needed = len([role for role in roles
                              if role.startswith('osd')])
            host_vars['devices'] = get_scratch_devices(remote)[0:dev_needed]
        if 'monitor_interface' not in extra_vars:
            host_vars['monitor_interface'] = remote.interface
        if 'radosgw_interface' not in extra_vars:
            host_vars['radosgw_interface'] = remote.interface
        if 'public_network' not in extra_vars:
            host_vars['public_network'] = remote.cidr
        return host_vars

    def run_rh_playbook(self):
        ceph_installer = self.ceph_installer
        args = self.args
        ceph_installer.run(args=[
            'cp',
            '-R',
            '/usr/share/ceph-ansible',
            '.'
        ])
        self._copy_and_print_config()
        out = StringIO()
        str_args = ' '.join(args)
        ceph_installer.run(
            args=[
                'cd',
                'ceph-ansible',
                run.Raw(';'),
                run.Raw(str_args)
            ],
            timeout=4200,
            check_status=False,
            stdout=out
        )
        log.info(out.getvalue())
        if re.search(r'all hosts have already failed', out.getvalue()):
            log.error("Failed during ceph-ansible execution")
            raise CephAnsibleError("Failed during ceph-ansible execution")
        self._create_rbd_pool()

    def run_playbook(self):
        # setup ansible on first mon node
        ceph_installer = self.ceph_installer
        args = self.args
        if ceph_installer.os.package_type == 'rpm':
            # handle selinux init issues during purge-cluster
            # https://bugzilla.redhat.com/show_bug.cgi?id=1364703
            ceph_installer.run(
                args=[
                    'sudo', 'yum', 'remove', '-y', 'libselinux-python'
                ]
            )
            # install crypto/selinux packages for ansible
            ceph_installer.run(args=[
                'sudo',
                'yum',
                'install',
                '-y',
                'libffi-devel',
                'python-devel',
                'openssl-devel',
                'libselinux-python'
            ])
        else:
            # update ansible from ppa
            ceph_installer.run(args=[
                'sudo',
                'add-apt-repository',
                run.Raw('ppa:ansible/ansible'),
            ])
            ceph_installer.run(args=[
                'sudo',
                'apt-get',
                'update',
            ])
            ceph_installer.run(args=[
                'sudo',
                'apt-get',
                'install',
                '-y',
                'ansible',
                'libssl-dev',
                'python-openssl',
                'libffi-dev',
                'python-dev'
            ])
        ansible_repo = self.config['repo']
        branch = 'master'
        if self.config.get('branch'):
            branch = self.config.get('branch')
        ansible_ver = 'ansible==2.3.2'
        if self.config.get('ansible-version'):
            ansible_ver = 'ansible==' + self.config.get('ansible-version')
        ceph_installer.run(
            args=[
                'rm',
                '-rf',
                run.Raw('~/ceph-ansible'),
                ],
            check_status=False
        )
        ceph_installer.run(args=[
            'mkdir',
            run.Raw('~/ceph-ansible'),
            run.Raw(';'),
            run.Raw('cd ~'),
            run.Raw(';'),
            'git',
            'clone',
            run.Raw('-b %s' % branch),
            run.Raw(ansible_repo),
        ])
        self._copy_and_print_config()
        str_args = ' '.join(args)
        ceph_installer.run(args=[
            run.Raw('cd ~/ceph-ansible'),
            run.Raw(';'),
            'virtualenv',
            run.Raw('--system-site-packages'),
            'venv',
            run.Raw(';'),
            run.Raw('source venv/bin/activate'),
            run.Raw(';'),
            'pip',
            'install',
            '--upgrade',
            'pip',
            run.Raw(';'),
            'pip',
            'install',
            run.Raw('setuptools>=11.3'),
            run.Raw(ansible_ver),
        ])
        ceph_installer.run(args=[
            run.Raw('cd ~/ceph-ansible'),
            run.Raw(';'),
            run.Raw(str_args)
        ])
        wait_for_health = self.config.get('wait-for-health', True)
        if wait_for_health:
            self.wait_for_ceph_health()
        # for the teuthology workunits to work we
        # need to fix the permission on keyring to be readable by them
        self._create_rbd_pool()
        self.fix_keyring_permission()

    def _copy_and_print_config(self):
            ceph_installer = self.ceph_installer
            # copy the inventory file to installer node
            ceph_installer.put_file(self.inventory, 'ceph-ansible/inven.yml')
            # copy the config provided site file or use sample
            if self.playbook_file is not None:
                ceph_installer.put_file(self.playbook_file, 'ceph-ansible/site.yml')
            else:
                # use the site.yml.sample provided by the repo as the main site.yml file
                ceph_installer.run(
                   args=[
                        'cp',
                        'ceph-ansible/site.yml.sample',
                        'ceph-ansible/site.yml'
                        ]
                )
            # copy extra vars to groups/all
            ceph_installer.put_file(self.extra_vars_file, 'ceph-ansible/group_vars/all')
            # print for debug info
            ceph_installer.run(args=('cat', 'ceph-ansible/inven.yml'))
            ceph_installer.run(args=('cat', 'ceph-ansible/site.yml'))
            ceph_installer.run(args=('cat', 'ceph-ansible/group_vars/all'))

    def _create_rbd_pool(self):
        mon_node = self.ceph_installer
        log.info('Creating RBD pool')
        mon_node.run(
            args=[
                'sudo', 'ceph', '--cluster', self.cluster_name,
                'osd', 'pool', 'create', 'rbd', '128', '128'],
            check_status=False)
        mon_node.run(
            args=[
                'sudo', 'ceph', '--cluster', self.cluster_name,
                'osd', 'pool', 'application', 'enable',
                'rbd', 'rbd', '--yes-i-really-mean-it'
                ],
            check_status=False)

    def fix_keyring_permission(self):
        clients_only = lambda role: role.startswith('client')
        for client in self.cluster.only(clients_only).remotes.iterkeys():
            client.run(args=[
                'sudo',
                'chmod',
                run.Raw('o+r'),
                '/etc/ceph/%s.client.admin.keyring' % self.cluster_name
            ])


class CephAnsibleError(Exception):
    pass

task = CephAnsible
