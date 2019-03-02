import logging
import yaml

from . import Task
from cStringIO import StringIO

from tempfile import NamedTemporaryFile
from teuthology.orchestra import run
from teuthology.misc import install_package
log = logging.getLogger(__name__)


class kube_setup(Task):
    name = 'kube_setup'

    """
    A task to setup kubernetes cluster using kubespray

    - kube_setup:
        repo: {git_base}kube-spray.git
        release: v2.8.2 (default is v2.8.3)
        vars:
            cert_management: None
            var1: value1

        Roles Usage:
        [Kmaster.0, Ketcd.0]
        [mon.a, Knode.0]
        [osd.0, Knode.1]

        Task Usage:
          - ssh-keys:
          - kube_setup:
    """

    groups_to_roles = dict(
            all='K',
            master='Kmaster',
            etcd='Ketcd',
            node='Knode',
        )
    kubespray_git = 'https://github.com/kubernetes-sigs/kubespray.git'

    def __init__(self, ctx, config):
        super(kube_setup, self).__init__(ctx, config)
        config = self.config or dict()
        self.playbook = None
        self.release = config.get('release', 'v2.8.3')
        if 'repo' not in config:
            self.config['repo'] = self.kubespray_git
        if 'vars' not in config:
            vars = dict()
            config['vars'] = vars
        vars = config['vars']

    def setup(self):
        super(kube_setup, self).setup()
        # generate hosts file based on test config
        self.generate_hosts_file()
        # everything from vars in config go into group_vars/all file
        extra_vars = dict()
        extra_vars.update(self.config.get('vars', dict()))
        self.extra_vars_file = None
        if len(extra_vars) > 0:
            gvar = yaml.dump(extra_vars, default_flow_style=False)
            self.extra_vars_file = self._write_hosts_file(
                                        prefix='kube_spray_gvar',
                                        content=gvar)

    def begin(self):
        super(kube_setup, self).begin()
        self.execute_playbook()

    def generate_hosts_file(self):
        hosts_dict = dict()
        for group in sorted(self.groups_to_roles.keys()):
            role_prefix = self.groups_to_roles[group]
            want = lambda role: role.startswith(role_prefix)
            for (remote, roles) in self.cluster.only(want).remotes.iteritems():
                hostname = remote.hostname
                if group.startswith('master') or group.startswith('node'):
                    group_name = 'kube-' + group
                else:
                    group_name = group
                if group_name not in hosts_dict:
                    hosts_dict[group_name] = {}

                if group_name == 'all':
                    vars = "ip={ip} ansible_host={ip}".format(ip=remote.ip_address)
                    hosts_dict[group_name][hostname] = hostname + " " + vars
                else:
                    hosts_dict[group_name][hostname] = hostname

        hosts_stringio = StringIO()
        for group in sorted(hosts_dict.keys()):
            hosts_stringio.write('[%s]\n' % group)
            for host in sorted(hosts_dict[group].keys()):
                host_line = hosts_dict[group][host]
                hosts_stringio.write('%s\n' % host_line)
            hosts_stringio.write('\n')
        # Add the final k8s-cluster: group
        hosts_stringio.write('\n[k8s-cluster:children]\n')
        hosts_stringio.write('kube-master\nkube-node\n')
        hosts_stringio.seek(0)
        self.inventory = self._write_hosts_file(prefix='kube_hosts_',
                                                content=hosts_stringio.read().strip())

    def _write_hosts_file(self, prefix, content):
        """
        Actually write the hosts file
        """
        hosts_file = NamedTemporaryFile(prefix=prefix,
                                        delete=False)
        hosts_file.write(content)
        hosts_file.flush()
        return hosts_file.name

    def run_pre_req(self):
        """
        Install required pre-requistes on each node for kubernetes
        cluster
        """
        for remote in self.cluster.remotes.keys():
            remote.run(args=[
                    'sudo', 'sytemctl', 'firewalld', 'disable'
            ])
            install_package('ansible', remote)

    def execute_playbook(self):
        """"
        run kubespray playbook as defined in usage
        refer https://github.com/kubernetes-sigs/kubespray
        """
        args = [
            'ANSIBLE_STDOUT_CALLBACK=debug',
            'ansible-playbook', '-vv',
            '-i', 'inventory/mycluster/hosts.ini',
            '--become', '--become-user=root', 'cluster.yml'
        ]
        (kube_installer,) = self.ctx.cluster.only('Kmaster.0').remotes.iterkeys()
        self.kube_installer = kube_installer
        self.run_pre_req()
        kube_installer.run(
            args=[
                'rm',
                '-rf',
                run.Raw('~/kubespray'),
                ],
            check_status=False
        )
        kube_installer.run(args=[
            'git',
            'clone',
            '-b',
            self.release,
            run.Raw(self.kubespray_git),
        ])
        kube_installer.run(args=[
            'cp', '-rfp',
            'kubespray/inventory/sample', 'kubespray/inventory/mycluster'
        ])
        # copy inventory file
        kube_installer.put_file(self.inventory,
                                'kubespray/inventory/mycluster/hosts.ini')

        # cat inventory file
        kube_installer.run(args=[
                    'cat', 'kubespray/inventory/mycluster/hosts.ini'
        ])

        # copy extra vars to groups/all
        if self.extra_vars_file:
            kube_installer.put_file(
                           self.extra_vars_file,
                           'kubespray/inventory/mycluster/group_vars/all')

        str_args = ' '.join(args)
        kube_installer.run(args=[
            run.Raw('cd ~/kubespray'),
            run.Raw(';'),
            'virtualenv',
            run.Raw('--system-site-packages'),
            'venv',
            run.Raw(';'),
            run.Raw('source venv/bin/activate'),
            run.Raw(';'),
            'pip',
            'install',
            '-r',
            'requirements.txt',
            run.Raw(';'),
            run.Raw(str_args)
        ])


task = kube_setup
