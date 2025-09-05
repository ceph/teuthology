import json
import logging
import os
import subprocess
import tempfile
import yaml

from teuthology.config import config
from teuthology.contextutil import safe_while
from teuthology.misc import decanonicalize_hostname
from teuthology.misc import deep_merge
from teuthology.lock import query

log = logging.getLogger(__name__)


def get_types():
    types = ['vps']
    if 'downburst' in config and 'machine' in config.downburst:
        machine = config.downburst.get('machine')
        if isinstance(machine, list):
            types = list(m.get('type') for m in machine)
    return types


def downburst_executable():
    """
    First check for downburst in the user's path.
    Then check in ~/src, ~ubuntu/src, and ~teuthology/src.
    Return '' if no executable downburst is found.
    """
    if config.downburst:
        if isinstance(config.downburst, dict):
            if 'path' in config.downburst:
                return config.downburst['path']
        else:
            return config.downburst
    path = os.environ.get('PATH', None)
    if path:
        for p in os.environ.get('PATH', '').split(os.pathsep):
            pth = os.path.join(p, 'downburst')
            if os.access(pth, os.X_OK):
                return pth
    import pwd
    little_old_me = pwd.getpwuid(os.getuid()).pw_name
    for user in [little_old_me, 'ubuntu', 'teuthology']:
        pth = os.path.expanduser(
            "~%s/src/downburst/virtualenv/bin/downburst" % user)
        if os.access(pth, os.X_OK):
            return pth
    return ''


def downburst_environment():
    env = dict()
    env['PATH'] = os.environ.get('PATH')
    discover_url = os.environ.get('DOWNBURST_DISCOVER_URL')
    if config.downburst and not discover_url:
        if isinstance(config.downburst, dict):
            discover_url = config.downburst.get('discover_url')
    if discover_url:
        env['DOWNBURST_DISCOVER_URL'] = discover_url
    return env


class Downburst(object):
    """
    A class that provides methods for creating and destroying virtual machine
    instances using downburst: https://github.com/ceph/downburst
    """
    def __init__(self, name, os_type, os_version, status=None, user='ubuntu',
                 logfile=None):
        self.name = name
        self.shortname = decanonicalize_hostname(self.name)
        self.os_type = os_type
        self.os_version = os_version
        self.status = status or query.get_status(self.name)
        self.config_path = None
        self.user_path = None
        self.user = user
        self.logfile = logfile
        self.host = decanonicalize_hostname(self.status['vm_host']['name'])
        self.executable = downburst_executable()
        self.environment = downburst_environment()

    def create(self):
        """
        Launch a virtual machine instance.

        If creation fails because an instance with the specified name is
        already running, first destroy it, then try again. This process will
        repeat two more times, waiting 60s between tries, before giving up.
        """
        if not self.executable:
            log.error("No downburst executable found.")
            return False
        self.build_config()
        success = None
        with safe_while(sleep=60, tries=3,
                        action="downburst create") as proceed:
            while proceed():
                (returncode, stdout, stderr) = self._run_create()
                log.info(stdout)
                log.info(stderr)
                if returncode == 0:
                    log.info("Downburst created %s: %s" % (self.name,
                                                           stdout.strip()))
                    success = True
                    break
                elif stderr:
                    # If the guest already exists first destroy then re-create:
                    if 'exists' in stderr:
                        success = False
                        log.info("Guest files exist. Re-creating guest: %s" %
                                 (self.name))
                        self.destroy()
                    else:
                        success = False
                        log.error("Downburst failed on %s" % self.name)
                        for i in stderr.split('\n'):
                            log.error(f">>> {i}")
                        break
            return success

    def _run_create(self):
        """
        Used by create(), this method is what actually calls downburst when
        creating a virtual machine instance.
        """
        if not self.config_path:
            raise ValueError("I need a config_path!")
        if not self.user_path:
            raise ValueError("I need a user_path!")

        args = [self.executable, '-v', '-c', self.host]
        if self.logfile:
            args.extend(['-l', self.logfile])
        args.extend([
            'create',
            '--wait',
            '--meta-data=%s' % self.config_path,
            '--user-data=%s' % self.user_path,
            self.shortname,
        ])
        log.info("Provisioning a {distro} {distroversion} vps".format(
            distro=self.os_type,
            distroversion=self.os_version
        ))
        log.debug(args)
        proc = subprocess.Popen(args, universal_newlines=True,
                                env=self.environment,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        out, err = proc.communicate()
        return (proc.returncode, out, err)

    def destroy(self):
        """
        Destroy (shutdown and delete) a virtual machine instance.
        """
        executable = self.executable
        if not executable:
            log.error("No downburst executable found.")
            return False
        args = [executable, '-v', '-c', self.host]
        if self.logfile:
            args.extend(['-l', self.logfile])
        args.extend(['destroy', self.shortname])
        log.debug(args)
        proc = subprocess.Popen(args, universal_newlines=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,)
        out, err = proc.communicate()
        log.info(out)
        log.info(err)
        if proc.returncode != 0:
            not_found_msg = "no domain with matching name '%s'" % self.shortname
            if not_found_msg in err:
                log.warning("Ignoring error during destroy: %s", err)
                return True
            log.error("Error destroying %s: %s", self.name, err)
            return False
        else:
            out_str = ': %s' % out if out else ''
            log.info("Destroyed %s%s" % (self.name, out_str))
            return True

    def build_config(self):
        """
        Assemble a configuration to pass to downburst, and write it to a file.
        """
        config_fd = tempfile.NamedTemporaryFile(delete=False, mode='wt')

        os_type = self.os_type.lower()
        os_version = self.os_version.lower()

        mac_address = self.status['mac_address']
        machine = dict(
            disk=os.environ.get('DOWNBURST_DISK_SIZE', '100G'),
            ram=os.environ.get('DOWNBURST_RAM_SIZE', '3.8G'),
            cpus=int(os.environ.get('DOWNBURST_CPUS', 1)),
            volumes=dict(
                count=int(os.environ.get('DOWNBURST_EXTRA_DISK_NUMBER', 4)),
                size=os.environ.get('DOWNBURST_EXTRA_DISK_SIZE', '100G'),
            ),
        )
        def belongs_machine_type(machine_config: dict, machine_type: str) -> bool:
            if isinstance(machine_config, dict):
                t = machine_config.get('type', None)
                if isinstance(t, str):
                    return machine_type == t
                elif isinstance(t, list):
                    return machine_type in t
            return False
        if isinstance(config.downburst, dict) and isinstance(config.downburst.get('machine'), list):
            machine_type = self.status['machine_type']
            machine_config = next((m for m in config.downburst.get('machine')
                        if belongs_machine_type(m, machine_type)), None)
            if machine_config is None:
                raise RuntimeError(f"Cannot find config for machine type {machine_type}.")
        elif isinstance(config.downburst, dict) and isinstance(config.downburst.get('machine'), dict):
            machine_config = config.downburst.get('machine')
        deep_merge(machine, machine_config)
        log.debug('Using machine config: %s', machine)
        file_info = {
            'disk-size': machine['disk'],
            'ram': machine['ram'],
            'cpus': machine['cpus'],
            'networks': [
                {'source': 'front', 'mac': mac_address}],
            'distro': os_type,
            'distroversion': self.os_version,
            'additional-disks': machine['volumes']['count'],
            'additional-disks-size': machine['volumes']['size'],
            'arch': 'x86_64',
        }
        fqdn = self.name.split('@')[-1]
        file_out = {
            'downburst': file_info,
            'local-hostname': fqdn,
        }
        yaml.safe_dump(file_out, config_fd)
        self.config_path = config_fd.name

        user_info = {
            'user': self.user,
            # Remove the user's password so console logins are possible
            'runcmd': [
                ['passwd', '-d', self.user],
            ]
        }
        # for opensuse-15.2 we need to replace systemd-logger with rsyslog for teuthology
        if os_type == 'opensuse' and os_version == '15.2':
            user_info['runcmd'].extend([
                ['zypper', 'rm', '-y', 'systemd-logger'],
                ['zypper', 'in', '-y', 'rsyslog'],
            ])
        # Install git on downbursted VMs to clone upstream linux-firmware.
        # Issue #17154
        if 'packages' not in user_info:
            user_info['packages'] = list()
        user_info['packages'].extend([
            'git',
            'wget',
        ])
        if os_type in ('centos', 'opensuse'):
            user_info['packages'].extend([
                'chrony',
            ])
        if os_type in ('ubuntu', 'debian'):
            user_info['packages'].extend([
                'ntp',
            ])

        # On CentOS/RHEL/Fedora, write the correct mac address and
        if os_type in ['centos', 'rhel', 'fedora']:
            user_info['runcmd'].extend([
                ['sed', '-ie', 's/HWADDR=".*"/HWADDR="%s"/' % mac_address,
                 '/etc/sysconfig/network-scripts/ifcfg-eth0'],
            ])
        # On Ubuntu, starting with 16.04, and Fedora, starting with 24, we need
        # to install 'python' to get python2.7, which ansible needs
        if os_type in ('ubuntu', 'fedora'):
            user_info['packages'].append('python')
        if os_type in ('centos'):
            user_info['packages'].extend([
                'python3-pip',
                'bind-utils',
            ])
        user_fd = tempfile.NamedTemporaryFile(delete=False, mode='wt')
        user_str = "#cloud-config\n" + yaml.safe_dump(user_info)
        user_fd.write(user_str)
        self.user_path = user_fd.name
        return True

    def remove_config(self):
        """
        Remove the downburst configuration file created by build_config()
        """
        if self.config_path and os.path.exists(self.config_path):
            os.remove(self.config_path)
            self.config_path = None
            return True
        if self.user_path and os.path.exists(self.user_path):
            os.remove(self.user_path)
            self.user_path = None
            return True
        return False

    def __del__(self):
        self.remove_config()


_known_downburst_distros = {
    'rhel_minimal': ['6.4', '6.5'],
    'centos': ['9.stream', '10.stream'],
    'centos_minimal': ['6.4', '6.5'],
    'debian': ['6.0', '7.0', '7.9', '8.0'],
    'fedora': ['41', '42'],
    'opensuse': ['1.0(tumbleweed)',
                 '15.5(leap)', '15.6(leap)',
                 '16.0(leap)',
        ],
    'sles': ['12-sp3', '15-sp1', '15-sp2'],
    'alma': ['10.0', '8.10', '9.6'],
    'rocky': ['10.0', '8.10', '9.6'],
    'ubuntu': ['20.04(focal)', '20.10(groovy)',
               '21.04(hirsute)', '21.10(impish)',
               '22.04(jammy)', '22.10(kinetic)',
               '23.04(lunar)', '23.10(mantic)',
               '24.04(noble)', '24.10(oracular)',
               '25.04(plucky)',
        ],
}

def get_distro_from_downburst():
    """
    Return a table of valid distros.

    If downburst is in path use it.  If either downburst is unavailable,
    or if downburst is unable to produce a json list, then use a default
    table or a table from previous successful call.
    """
    # because sometimes downburst fails to complete list-json
    # due to temporary issues with vendor site accessibility
    # we cache known downburst distros from previous call
    # to be reused in such cases of outage
    global _known_downburst_distros
    executable_cmd = downburst_executable()
    environment_dict = downburst_environment()
    if not executable_cmd:
        log.warning("Downburst not found!")
        log.info('Using default values for supported os_type/os_version')
        return _known_downburst_distros
    try:
        log.debug(executable_cmd)
        output = subprocess.check_output([executable_cmd, 'list-json'],
                                                        env=environment_dict)
        _known_downburst_distros = json.loads(output)
        return _known_downburst_distros
    except (subprocess.CalledProcessError, OSError):
        log.exception("Error calling downburst!")
        log.info('Using default values for supported os_type/os_version or values from previous call...')
        return _known_downburst_distros
