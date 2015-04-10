import logging
import os
import subprocess
import tempfile
import xmlrpclib
import yaml

from .config import config
from .contextutil import safe_while
from .misc import decanonicalize_hostname, get_distro, get_distro_version
from .lockstatus import get_status
from .orchestra.remote import Remote


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
    def __init__(self, name, os_type, os_version, status=None):
        self.name = name
        self.os_type = os_type
        self.os_version = os_version
        self.status = status or get_status(self.name)
        self.config_path = None
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
                        log.info("Downburst failed on %s: %s" % (
                            self.name, stderr.strip()))
                        break
            return success

    def _run_create(self):
        """
        Used by create(), this method is what actually calls downburst when
        creating a virtual machine instance.
        """
        if not self.config_path:
            raise ValueError("I need a config_path!")
        shortname = decanonicalize_hostname(self.name)

        args = [self.executable, '-c', self.host, 'create',
                '--meta-data=%s' % self.config_path, shortname,
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

        file_info = {
            'disk-size': '100G',
            'ram': '1.9G',
            'cpus': 1,
            'networks': [
                {'source': 'front', 'mac': self.status['mac_address']}],
            'distro': self.os_type.lower(),
            'distroversion': self.os_version,
            'additional-disks': 3,
            'additional-disks-size': '200G',
            'arch': 'x86_64',
        }
        fqdn = self.name.split('@')[1]
        file_out = {'downburst': file_info, 'local-hostname': fqdn}
        yaml.safe_dump(file_out, config_fd)
        self.config_path = config_fd.name
        return True

    def remove_config(self):
        """
        Remove the downburst configuration file created by build_config()
        """
        if self.config_path and os.path.exists(self.config_path):
            os.remove(self.config_path)
            self.config_path = None
            return True
        return False

    def __del__(self):
        self.remove_config()


def create_if_vm(ctx, machine_name, _downburst=None):
    """
    Use downburst to create a virtual machine

    :param _downburst: Only used for unit testing.
    """
    if _downburst:
        status_info = _downburst.status
    else:
        status_info = get_status(machine_name)
    if not status_info.get('is_vm', False):
        return False
    os_type = get_distro(ctx)
    os_version = get_distro_version(ctx)

    has_config = hasattr(ctx, 'config') and ctx.config is not None
    if has_config and 'downburst' in ctx.config:
        log.warning(
            'Usage of a custom downburst config has been deprecated.'
        )

    dbrst = _downburst or Downburst(name=machine_name, os_type=os_type,
                                    os_version=os_version, status=status_info)
    return dbrst.create()


def destroy_if_vm(ctx, machine_name, user=None, description=None,
                  _downburst=None):
    """
    Use downburst to destroy a virtual machine

    Return False only on vm downburst failures.

    :param _downburst: Only used for unit testing.
    """
    if _downburst:
        status_info = _downburst.status
    else:
        status_info = get_status(machine_name)
    if not status_info or not status_info.get('is_vm', False):
        return True
    if user is not None and user != status_info['locked_by']:
        msg = "Tried to destroy {node} as {as_user} but it is locked " + \
            "by {locked_by}"
        log.error(msg.format(node=machine_name, as_user=user,
                             locked_by=status_info['locked_by']))
        return False
    if (description is not None and description !=
            status_info['description']):
        msg = "Tried to destroy {node} with description {desc_arg} " + \
            "but it is locked with description {desc_lock}"
        log.error(msg.format(node=machine_name, desc_arg=description,
                             desc_lock=status_info['description']))
        return False
    dbrst = _downburst or Downburst(name=machine_name, os_type=None,
                                    os_version=None, status=status_info)
    return dbrst.destroy()


class Cobbler(object):
    def __init__(self, name, os_type, os_version, status=None):
        self.name = name
        self.os_type = os_type
        self.os_version = os_version
        #self.status = status or get_status(self.name)
        self.server = config.cobbler_server
        self.user = config.cobbler_user
        self.password = config.cobbler_password
        self._connection = None
        self._token = None
        self._system_handle = None

    def provision(self):
        self.set_profile()
        self.set_netboot()
        self.save_system()
        self.reboot()

    @property
    def connection(self):
        # We need to us isinstance because "if _connection" calls bool(), which
        # is unimplemented by xmlrpclib.ServerProxy
        have_connection = isinstance(self._connection, xmlrpclib.ServerProxy)
        if not have_connection or not self._token:
            self._connect()
        return self._connection

    @property
    def token(self):
        # We need to us isinstance because "if _connection" calls bool(), which
        # is unimplemented by xmlrpclib.ServerProxy
        have_connection = isinstance(self._connection, xmlrpclib.ServerProxy)
        if not self._token or not have_connection:
            self._connect()
        return self._token

    def _connect(self):
        if not self.server:
            raise ValueError("config.cobbler_server not set!")
        elif not self.user:
            raise ValueError("config.cobbler_user not set!")
        elif not self.password:
            raise ValueError("config.cobbler_password not set!")
        self._connection = xmlrpclib.Server(self.server)
        self._token = self._connection.login(self.user, self.password)

    @property
    def system_handle(self):
        if not self._system_handle:
            self._system_handle = self.connection.get_system_handle(self.name,
                                                                    self.token)
        return self._system_handle

    def find_profile(self):
        profiles = self.connection.find_profile(dict(
            name="*{os_type}*{os_version}*".format(
                os_type=self.os_type.lower(), os_version=self.os_version)
            ))
        return profiles[0]

    def set_profile(self):
        self.profile = self.find_profile()
        log.info('Using profile {profile} for {node}'.format(
            profile=self.profile, node=self.name)
        )
        return self.connection.modify_system(
            self.system_handle, 'profile', self.profile, self.token)

    def set_netboot(self):
        log.info('Enabling netboot on {node}'.format(
            node=self.name)
        )
        return self.connection.modify_system(
            self.system_handle, 'netboot_enabled', True, self.token)

    def save_system(self):
        log.info('Saving system {node}'.format(
            node=self.name)
        )
        return self.connection.save_system(self.system_handle, self.token)

    def reboot(self):
        log.info('Rebooting {node}'.format(
            node=self.name)
        )
        return self.connection.power_system(
            self.system_handle, 'reboot', self.token)

    def wait_for_remote(self, timeout=1200):
        self.remote = Remote(self.name)
        return self.remote.reconnect(timeout=timeout)
