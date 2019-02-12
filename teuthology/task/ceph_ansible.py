import json
import os
import re
import logging
import yaml
import time
import errno
import socket
from cStringIO import StringIO

from . import Task
from tempfile import NamedTemporaryFile
from ..config import config as teuth_config
from ..misc import get_scratch_devices
from teuthology import contextutil
from teuthology.orchestra import run
from teuthology.orchestra.daemon import DaemonGroup
from teuthology.task.install import ship_utilities
from teuthology import misc
from teuthology import misc as teuthology

log = logging.getLogger(__name__)


class CephAnsible(Task):
    name = 'ceph_ansible'

    __doc__ = """
    A task to setup ceph cluster using ceph-ansible

    - ceph-ansible:
        cluster: 'cluster_name' # arbitrary cluster identifier defined in rgw test suite yamls 
        in case of multisite 
        repo: {git_base}ceph-ansible.git
        branch: mybranch # defaults to master
        ansible-version: 2.4 # defaults to 2.5
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

    The machine that ceph-ansible runs on can be specified using the
    installer.0 role.  If installer.0 is not used, the first mon will be the
    machine on which ceph-ansible runs.
    """.format(git_base=teuth_config.ceph_git_base_url)

    groups_to_roles = dict(
        mons='mon',
        mgrs='mgr',
        mdss='mds',
        osds='osd',
        rgws='rgw',
        clients='client',
        nfss='nfs',
        haproxys='haproxy'
    )

    def __init__(self, ctx, config):
        super(CephAnsible, self).__init__(ctx, config)
        config = self.config or dict()
        self.playbook = None
        self.cluster_groups_to_roles = None
        self.ready_cluster = None
        if 'playbook' in config:
            self.playbook = self.config['playbook']
        if 'repo' not in config:
            self.config['repo'] = os.path.join(teuth_config.ceph_git_base_url,
                                               'ceph-ansible.git')

        if 'cluster' in config:
            self.cluster_name = self.config.get('cluster')
        else:
            self.cluster_name = None

        # Legacy option set to true in case we are running a test
        # which was earlier using "ceph" task for configuration
        self.legacy = False
        if 'legacy' in config:
            self.legacy = True

        # default vars to dev builds
        if 'vars' not in config:
            vars = dict()
            config['vars'] = vars
        vars = config['vars']

        # for downstream bulids skip var setup
        if 'rhbuild' in config:
            return
        if 'ceph_dev' not in vars:
            vars['ceph_dev'] = True
        if 'ceph_dev_key' not in vars:
            vars['ceph_dev_key'] = 'https://download.ceph.com/keys/autobuild.asc'
        if 'ceph_dev_branch' not in vars:
            vars['ceph_dev_branch'] = ctx.config.get('branch', 'master')

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

    def remove_cluster_prefix(self):

        stripped_role = {}
        if self.cluster_name:
            self.each_cluster = self.ctx.cluster.only(lambda role: role.startswith(self.cluster_name))
            for remote, roles in self.each_cluster.remotes.iteritems():
                stripped_role[remote] = []
                for rol in roles:
                    stripped_role[remote].append(teuthology.ceph_role(rol))
            self.each_cluster.remotes = stripped_role
        else:
            self.each_cluster = self.ctx.cluster
        log.info('updated cluster {}'.format(self.each_cluster))

    def execute_playbook(self):
        """
        Execute ansible-playbook

        :param _logfile: Use this file-like object instead of a LoggerFile for
                         testing
        """

        args = [
            'ANSIBLE_STDOUT_CALLBACK=debug',
            'ansible-playbook', '-vv',
            '-e', 'check_firewall=false',
            '-i', 'inven.yml', 'site.yml'
        ]
        log.debug("Running %s", args)
        # If there is an installer.0 node, use that for the installer.
        # Otherwise, use the first mon node as installer node.
        ansible_loc = self.each_cluster.only('installer.0')
#        self.each_cluster = self.each_cluster.only(lambda role: role.startswith(self.cluster_name))
#        self.remove_cluster_prefix()
        (ceph_first_mon,) = self.ctx.cluster.only(
            misc.get_first_mon(self.ctx,
                               self.config, self.cluster_name)).remotes.iterkeys()
        if ansible_loc.remotes:
            (ceph_installer,) = ansible_loc.remotes.iterkeys()
        else:
            ceph_installer = ceph_first_mon
        self.ceph_first_mon = ceph_first_mon
        self.installer = ceph_installer
        self.ceph_installer = self.installer
        self.args = args
        # ship utilities files
        self._ship_utilities()
        if self.config.get('rhbuild'):
            self.run_rh_playbook()
            if self.config.get('haproxy', False):
                self.run_haproxy()
        else:
            self.run_playbook()
	'''Redundant call but required for coverage'''
        self._ship_utilities()

    def generate_hosts_file(self):

        hosts_dict = dict()
        self.remove_cluster_prefix()

        for group in sorted(self.groups_to_roles.keys()):
            role_prefix = self.groups_to_roles[group]
            log.info("role_prefix: ".format(role_prefix))
            want = lambda role: role.startswith(role_prefix)
            for (remote, roles) in self.each_cluster.only(want).remotes.iteritems():
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

    def add_osddisk_info(self, ctx, remote, json_dir, json_list):
        '''
        add output of diskinfo json to ctx
        format looks like
        {'osd.id':[{'osd_disk':'details'}, remote]}
        above dict will be added into ctx.osd_disk_info
        this also helps in mapping given osd to remote
        '''
        buf = ""
        for ent in json_list:
            if ent == '' or ent == '\n':
                continue
            buf = teuthology.get_file(remote, json_dir+ent)
            osd_info = json.loads(buf)
            log.info(osd_info)
            my_id = osd_info['whoami']
            temp_val = [osd_info, remote]
            ctx.osd_disk_info[my_id] = temp_val
            log.info("added with osd {}".format(my_id))

    def get_osd_disk_map(self, ctx, remote):
        '''
        Use ceph-volume to fetch all the disk details
        on the given remote
        '''
        osddir = '/var/lib/ceph/osd/'
        json_dir = '/etc/ceph/osd/'
        cmd = 'sudo ls ' + osddir
        proc = remote.run(
            args=cmd,
            stdout=StringIO(),
        )
        if not proc.stdout == None:
            out = proc.stdout.getvalue()
        elif not proc.stderr == None:
            out = proc.stderr.getvalue()
        else:
            log.info("No ouput from ls {}".format(osddir))
            assert False
        log.info("OSDs on this node are")
        log.info(out)
        olist = out.split('\n')
        log.info('OSD list = {}'.format(olist))
        for osd in olist:
            if osd == '':
                continue
            cmd = 'sudo ceph-volume simple scan {}'.format(osddir+osd)
            proc = remote.run(
                args=cmd,
                stdout=StringIO(),
            )

            if not proc.stdout == None:
                out = proc.stdout.getvalue()
            else:
                out = proc.stderr.getvalue()
            log.info(out)

        #Extract the results from /etc/ceph/osd which will have json file
        cmd = 'sudo ls ' + json_dir
        proc = remote.run(
            args=cmd,
            stdout=StringIO(),
        )
        if not proc.stdout == None:
            out = proc.stdout.getvalue()
        else:
            out = proc.stderr.getvalue()
        log.info(out)
        json_list = out.split('\n')
        self.add_osddisk_info(ctx, remote, json_dir, json_list)

    def set_diskinfo_ctx(self):
        '''
        This function get create a dict with disk information
        for corresponding osd
        '''
        ctx = self.ctx
        r = re.compile("osd.*")
        ctx.osd_disk_info = dict()
        for remote, roles in self.each_cluster.remotes.iteritems():
            log.info("Current node is {}".format(remote.name))
            log.info("Roles are {}".format(roles))
            newlist = filter(r.match, roles)
            if len(newlist) > 0:
                self.get_osd_disk_map(ctx, remote)
        log.info("osd disk info is ")
        log.info(ctx.osd_disk_info)

    def begin(self):
        super(CephAnsible, self).begin()
        self.execute_playbook()
#        self.set_diskinfo_ctx()

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
            path = os.path.join(ctx.archive, self.cluster_name if self.cluster_name else 'ceph', 'remote')
            try:
                os.makedirs(path)
            except OSError as e:
                if e.errno != errno.EISDIR or e.errno != errno.EEXIST:
                    raise

            def wanted(role):
                # Only attempt to collect logs from hosts which are part of the
                # cluster
                return any(map(
                    lambda role_stub: role.startswith(role_stub),
                    self.groups_to_roles.values(),
                ))

            for remote in self.each_cluster.only(wanted).remotes.keys():
                sub = os.path.join(path, remote.shortname)
                os.makedirs(sub)
                misc.pull_directory(remote, '/var/log/ceph',
                                    os.path.join(sub, 'log'))
		if ctx.config['coverage']:
		    cover_dir = os.path.join(sub, "coverage")
		    os.makedirs(cover_dir)
		    misc.pull_directory(remote, '/builddir',
					cover_dir)


    def wait_for_ceph_health(self):
        with contextutil.safe_while(sleep=15, tries=6,
                                    action='check health') as proceed:
            remote = self.ceph_first_mon
            remote.run(args=[
                'sudo', 'ceph', 'osd', 'tree'
            ])
            remote.run(args=[
                'sudo', 'ceph', '-s'
            ])
            log.info("Waiting for Ceph health to reach HEALTH_OK \
                        or HEALTH WARN")
            while proceed():
                out = StringIO()
                remote.run(
                    args=['sudo', 'ceph',
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
            roles = self.each_cluster.remotes[remote]
            dev_needed = len([role for role in roles
                              if role.startswith('osd')])
            host_vars['devices'] = get_scratch_devices(remote)[0:dev_needed]
            # check if the host has nvme device, if so use it as journal
            # fix me asap
            if extra_vars.get('osd_scenario') == 'non-collocated':
                journals = ['/dev/nvme0n1']
                host_vars['dedicated_devices'] = journals
                host_vars['devices'] = get_scratch_devices(remote)[0:1]
        if 'monitor_interface' not in extra_vars:
            host_vars['monitor_interface'] = remote.interface
        if 'radosgw_interface' not in extra_vars:
            host_vars['radosgw_interface'] = remote.interface
        if 'public_network' not in extra_vars:
            host_vars['public_network'] = remote.cidr
        return host_vars

    def run_rh_playbook(self):
        args = self.args
        ceph_installer = self.ceph_installer
        from tasks.set_repo import GA_BUILDS, set_cdn_repo
        rhbuild = self.config.get('rhbuild')
        # skip cdn's for rhel beta tests which will use GA builds from Repo
        if self.ctx.config.get('redhat').get('skip-subscription-manager',
                                             False) is False:
            if rhbuild in GA_BUILDS:
                set_cdn_repo(self.ctx, self.config)
        # install ceph-ansible
        if ceph_installer.os.package_type == 'rpm':
            ceph_installer.run(args=[
                'sudo',
                'yum',
                'install',
                '-y',
                'ceph-ansible'])
            time.sleep(4)
        else:
            ceph_installer.run(args=[
                'sudo',
                'apt-get',
                'install',
                '-y',
                'ceph-ansible'])
            time.sleep(4)
        ceph_installer.run(args=[
            'cp',
            '-R',
            '/usr/share/ceph-ansible',
            '.'
        ])
        self._copy_and_print_config()
        self._generate_client_config()
        str_args = ' '.join(args)
        ceph_installer.run(
            args=[
                'cd',
                'ceph-ansible',
                run.Raw(';'),
                run.Raw(str_args)
            ],
            timeout=4200,
        )
        self.ready_cluster = self.each_cluster
        log.info('Ready_cluster {}'.format(self.ready_cluster))
	self._ship_utilities()
        self._create_rbd_pool()
        self._fix_roles_map()
        # fix keyring permission for workunits
        self.fix_keyring_permission()
        self.create_keyring()
        if self.legacy:
            self.change_key_permission()
        self.wait_for_ceph_health()

    def run_haproxy(self):

        """
        task:
            ceph-ansible:
                haproxy: true
                haproxy_repo: https://github.com/smanjara/ansible-haproxy.git
                haproxy_branch: master
        """
        # Clone haproxy from https://github.com/smanjara/ansible-haproxy/,
        # use inven.yml from ceph-ansible dir to read haproxy node from
        # Assumes haproxy roles such as haproxy.0, haproxy.1 and so on.

        installer_node = self.ceph_installer
        haproxy_ansible_repo = self.config['haproxy_repo']
        branch = 'master'
        if self.config.get('haproxy_branch'):
            branch = self.config.get('haproxy_branch')

        installer_node.run(args=[
            'cd',
            run.Raw('~/'),
            run.Raw(';'),
            'git',
            'clone',
            run.Raw('-b %s' % branch),
            run.Raw(haproxy_ansible_repo),
        ],
            timeout=4200,
            stdout=StringIO()
        )
        allhosts = self.each_cluster.only(misc.is_type('rgw')).remotes.keys()
        clients = list(set(allhosts))
        ips = []
        for each_client in clients:
            ips.append(socket.gethostbyname(each_client.hostname))

        # substitute {{ ip_var' }} in haproxy.yml file with rgw node ips
        ip_vars = {}
        for i in range(len(ips)):
            ip_vars['ip_var' + str(i)] = ips.pop()

        # run haproxy playbook
        args = [
            'ANSIBLE_STDOUT_CALLBACK=debug',
            'ansible-playbook', '-vv', 'haproxy.yml',
            '-e', "'%s'" % json.dumps(ip_vars),
            '-i', '~/ceph-ansible/inven.yml'
        ]
        log.debug("Running %s", args)
        str_args = ' '.join(args)
        installer_node.run(
            args=[
                run.Raw('cd ~/ansible-haproxy'),
                run.Raw(';'),
                run.Raw(str_args)
            ]
        )
        # run keepalived playbook
        args = [
            'ANSIBLE_STDOUT_CALLBACK=debug',
            'ansible-playbook', '-vv', 'keepalived.yml',
            '-e', "'%s'" % json.dumps(ip_vars),
            '-i', '~/ceph-ansible/inven.yml'
        ]
        log.debug("Running %s", args)
        str_args = ' '.join(args)
        installer_node.run(
            args=[
                run.Raw('cd ~/ansible-haproxy'),
                run.Raw(';'),
                run.Raw(str_args)
            ]
        )

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
        ansible_ver = 'ansible==2.5'
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
            run.Raw('notario>=0.0.13'), # FIXME: use requirements.txt
            run.Raw('netaddr'),
            run.Raw(ansible_ver),
            run.Raw(';'),
            run.Raw(str_args)
        ])
	self._ship_utilities()
        wait_for_health = self.config.get('wait-for-health', True)
        if wait_for_health:
            self.wait_for_ceph_health()
        # for the teuthology workunits to work we
        # need to fix the permission on keyring to be readable by them
        self._create_rbd_pool()
        self._fix_roles_map()
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

            ceph_installer.run(args=('sed', '-i', '/defaults/ a\deprecation_warnings=False',
                                     'ceph-ansible/ansible.cfg'))

            # copy extra vars to groups/all
            ceph_installer.put_file(self.extra_vars_file, 'ceph-ansible/group_vars/all')
            # print for debug info
            ceph_installer.run(args=('cat', 'ceph-ansible/inven.yml'))
            ceph_installer.run(args=('cat', 'ceph-ansible/site.yml'))
            ceph_installer.run(args=('cat', 'ceph-ansible/group_vars/all'))

    def _ship_utilities(self):
        with ship_utilities(self.ctx, {'skipcleanup': True}) as ship_utils:
            ship_utils

    def _fix_roles_map(self):
        ctx = self.ctx
        if not hasattr(ctx, 'managers'):
            ctx.managers = {}
        ctx.daemons = DaemonGroup(use_systemd=True)
        if not hasattr(ctx, 'new_remote_role'):
            new_remote_role = dict()
            ctx.new_remote_role = new_remote_role
        else:
            new_remote_role = ctx.new_remote_role
        for remote, roles in self.ready_cluster.remotes.iteritems():
            new_remote_role[remote] = []
            generate_osd_list = True
            for role in roles:
                cluster, rol, id = misc.split_role(role)
                if rol.startswith('osd'):
                    if generate_osd_list:
                        # gather osd ids as seen on host
                        out = StringIO()
                        remote.run(args=[
                                        'ps', '-eaf', run.Raw('|'), 'grep',
                                        'ceph-osd', run.Raw('|'),
                                        run.Raw('awk {\'print $13\'}')],
                                   stdout=out)
                        osd_list_all = out.getvalue().split('\n')
                        generate_osd_list = False
                        osd_list = []
                        for osd_id in osd_list_all:
                            try:
                                if type(int(osd_id)) is int:
                                    osd_list.append(osd_id)
                            except ValueError:
                                # ignore any empty lines as part of output
                                pass
                    id = osd_list.pop()
                    log.info("Registering Daemon {rol} {id}".format(rol=rol, id=id))
                    ctx.daemons.add_daemon(remote, rol, id)
                    if len(role.split('.')) == 2:
                        osd_role = "{rol}.{id}".format(rol=rol, id=id)
                    else:
                        osd_role = "{c}.{rol}.{id}".format(c=cluster, rol=rol, id=id)
                    new_remote_role[remote].append(osd_role)
                elif rol.startswith('mon') or rol.startswith('mgr') or rol.startswith('mds'):
                    hostname = remote.shortname
                    new_remote_role[remote].append(role)
                    log.info("Registering Daemon {rol} {id}".format(rol=rol, id=id))
                    ctx.daemons.add_daemon(remote, rol, hostname)
                elif rol.startswith('rgw'):
                    hostname = remote.shortname
                    new_remote_role[remote].append(role)
                    log.info("Registering Daemon {rol} {id}".format(rol=rol, id=id))
                    ctx.daemons.add_daemon(remote, rol, id_='rgw.' + hostname)
                else:
                    new_remote_role[remote].append(role)
        self.each_cluster.remotes.update(new_remote_role)
        (ceph_first_mon,) = self.ctx.cluster.only(
            misc.get_first_mon(self.ctx,
                               self.config, self.cluster_name)).remotes.iterkeys()
        from tasks.ceph_manager import CephManager
        ctx.managers['ceph'] = CephManager(
            ceph_first_mon,
            ctx=ctx,
            logger=log.getChild('ceph_manager.' + 'ceph'),
            )

    def _generate_client_config(self):
        ceph_installer = self.ceph_installer
        ceph_installer.run(args=('touch', 'ceph-ansible/clients.yml'))
        # copy admin key for all clients
        ceph_installer.run(
                            args=[
                                run.Raw('printf "copy_admin_key: True\n"'),
                                run.Raw('>'),
                                'ceph-ansible/group_vars/clients'
                                ]
                           )
        ceph_installer.run(args=('cat', 'ceph-ansible/group_vars/clients'))

    def _create_rbd_pool(self):
        mon_node = self.ceph_first_mon
        log.info('Creating RBD pool')
        mon_node.run(
            args=[
                'sudo', 'ceph',
                'osd', 'pool', 'create', 'rbd', '128', '128'],
            check_status=False)
        mon_node.run(
            args=[
                'sudo', 'ceph',
                'osd', 'pool', 'application', 'enable',
                'rbd', 'rbd', '--yes-i-really-mean-it'
                ],
            check_status=False)

    def fix_keyring_permission(self):
        clients_only = lambda role: role.startswith('client')
        for client in self.each_cluster.only(clients_only).remotes.iterkeys():
            client.run(args=[
                'sudo',
                'chmod',
                run.Raw('o+r'),
                '/etc/ceph/ceph.client.admin.keyring'
            ])

    # this will be called only if "legacy" is true
    def change_key_permission(self):
        """
        Change permission for admin.keyring files on all nodes
        only if legacy is set to True
        """
        log.info("Changing permission for admin keyring on all nodes")
        mons = self.ctx.cluster.only(teuthology.is_type('mon', self.cluster_name))
        for remote, roles in mons.remotes.iteritems():
            remote.run(args=[
                'sudo',
                'chmod',
                run.Raw('o+r'),
                '/etc/ceph/%s.client.admin.keyring' % self.cluster_name,
                run.Raw('&&'),
                'sudo',
                'ls',
                run.Raw('-l'),
                '/etc/ceph/%s.client.admin.keyring' % self.cluster_name,
            ])

    def create_keyring(self):
        """
        Set up key ring on remote sites
        """
        log.info('Setting up client nodes...')
        clients = self.ctx.cluster.only(teuthology.is_type('client', self.cluster_name))
        testdir = teuthology.get_testdir(self.ctx)
        coverage_dir = '{tdir}/archive/coverage'.format(tdir=testdir)
        for remote, roles_for_host in clients.remotes.iteritems():
            for role in teuthology.cluster_roles_of_type(roles_for_host, 'client',
                                                        self.cluster_name):
                name = teuthology.ceph_role(role)
                log.info("Creating keyring for {}".format(name))
                client_keyring = '/etc/ceph/{0}.{1}.keyring'.format(self.cluster_name, name)
                remote.run(
                    args=[
                        'sudo',
                        'adjust-ulimits',
                        'ceph-coverage',
                        coverage_dir,
                        'ceph-authtool',
                        '--create-keyring',
                        '--gen-key',
                        # TODO this --name= is not really obeyed, all unknown "types" are munged to "client"
                        '--name={name}'.format(name=name),
                        '--cap',
                        'osd',
                        'allow rwx',
                        '--cap',
                        'mon',
                        'allow rwx',
                        client_keyring,
                        run.Raw('&&'),
                        'sudo',
                        'chmod',
                        '0644',
                        client_keyring,
                        run.Raw('&&'),
                        'sudo',
                        'ls',run.Raw('-l'),
                        client_keyring,
                        run.Raw('&&'),
                        'sudo',
                        'ceph',
                        'auth',
                        'import',
                        run.Raw('-i'),
                        client_keyring,
                        ],
                    )


class CephAnsibleError(Exception):
    pass

task = CephAnsible
