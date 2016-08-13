import logging
import os
import subprocess
import tempfile
import yaml

from ..compat import stringify
from ..config import config
from ..contextutil import safe_while
from ..misc import decanonicalize_hostname
from ..lockstatus import get_status


log = logging.getLogger(__name__)


def downburst_executable():
    """
    First check for downburst in the user's path.
    Then check in ~/src, ~ubuntu/src, and ~teuthology/src.
    Return '' if no executable downburst is found.
    """
    if config.downburst:
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


class Downburst(object):
    """
    A class that provides methods for creating and destroying virtual machine
    instances using downburst: https://github.com/ceph/downburst
    """
    def __init__(self, name, os_type, os_version, status=None, user='ubuntu'):
        self.name = name
        self.os_type = os_type
        self.os_version = os_version
        self.status = status or get_status(self.name)
        self.config_path = None
        self.user_path = None
        self.user = user
        self.host = decanonicalize_hostname(self.status['vm_host']['name'])
        self.executable = downburst_executable()

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
                if returncode == 0:
                    log.info("Downburst created %s: %s" % (self.name, stringify(
                                                           stdout.strip())))
                    success = True
                    break
                elif stderr:
                    # If the guest already exists first destroy then re-create:
                    if b'exists' in stderr:
                        success = False
                        log.info("Guest files exist. Re-creating guest: %s" %
                                 (self.name))
                        self.destroy()
                    else:
                        success = False
                        log.info("Downburst failed on %s: %s" % (
                            self.name, stringify(stderr.strip())))
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
        shortname = decanonicalize_hostname(self.name)

        args = [
            self.executable,
            '-c', self.host,
            'create',
            '--wait',
            '--meta-data=%s' % self.config_path,
            '--user-data=%s' % self.user_path,
            shortname,
        ]
        log.info("Provisioning a {distro} {distroversion} vps".format(
            distro=self.os_type,
            distroversion=self.os_version
        ))
        proc = subprocess.Popen(args, stdout=subprocess.PIPE,
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
        shortname = decanonicalize_hostname(self.name)
        args = [executable, '-c', self.host, 'destroy', shortname]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,)
        out, err = proc.communicate()
        if err:
            log.error("Error destroying {machine}: {msg}".format(
                machine=self.name, msg=err))
            return False
        elif proc.returncode == 0:
            out_str = ': %s' % out if out else ''
            log.info("Destroyed %s%s" % (self.name, out_str))
            return True
        else:
            log.error("I don't know if the destroy of {node} succeded!".format(
                node=self.name))
            return False

    def build_config(self):
        """
        Assemble a configuration to pass to downburst, and write it to a file.
        """
        config_fd = tempfile.NamedTemporaryFile(delete=False)

        os_type = self.os_type.lower()
        mac_address = self.status['mac_address']

        file_info = {
            'disk-size': '100G',
            'ram': '3.8G',
            'cpus': 1,
            'networks': [
                {'source': 'front', 'mac': mac_address}],
            'distro': os_type,
            'distroversion': self.os_version,
            'additional-disks': 3,
            'additional-disks-size': '200G',
            'arch': 'x86_64',
        }
        fqdn = self.name.split('@')[1]
        file_out = {
            'downburst': file_info,
            'local-hostname': fqdn,
        }
        yaml.safe_dump(file_out, config_fd, encoding='utf-8')
        self.config_path = config_fd.name

        user_info = {
            'user': self.user,
            # Remove the user's password so console logins are possible
            'runcmd': [
                ['passwd', '-d', self.user],
            ]
        }
        # On CentOS/RHEL/Fedora, write the correct mac address
        if os_type in ['centos', 'rhel', 'fedora']:
            user_info['runcmd'].extend([
                ['sed', '-ie', 's/HWADDR=".*"/HWADDR="%s"/' % mac_address,
                 '/etc/sysconfig/network-scripts/ifcfg-eth0'],
            ])
        # On Ubuntu, starting with 16.04, we need to install 'python' to get
        # python2.7, which ansible needs
        elif os_type == 'ubuntu':
            if 'packages' not in user_info:
                user_info['packages'] = list()
            user_info['packages'].extend([
                'python',
            ])
        user_fd = tempfile.NamedTemporaryFile(delete=False)
        yaml.safe_dump(user_info, user_fd, encoding='utf-8')
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
