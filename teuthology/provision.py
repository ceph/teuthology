import logging
import os
import subprocess
import tempfile
import yaml

from .config import config
from .contextutil import safe_while
from .misc import decanonicalize_hostname, get_distro, get_distro_version
import misc


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
        self.status = status or misc.get_status(self.name)
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


class OpenStack(object):
    """
    A class that provides methods for creating and destroying virtual machine
    instances using OpenStack
    """
    def __init__(self, name, status=None):
        self.name = name
        self.user_data = tempfile.mktemp()
        self.openstack = None
        for openstack in config.openstack['clusters'].keys():
            if name.startswith(openstack):
                self.openstack = config.openstack['clusters'][openstack]
                log.debug("OpenStack: " + name + " startswith " + openstack +
                          ", config " + str(self.openstack))
                break
        if not self.openstack:
            raise ValueError("machine " + name +
                             " is machine_type openstack " +
                             "but " + config.yaml_path +
                             " only knows about " +
                             str(config.openstack.keys()))
        self.status = status or misc.get_status(self.name)
        self.up_string = 'The system is finally up'

    def __del__(self):
        if os.path.exists(self.user_data):
            os.unlink(self.user_data)

    def init_user_data(self, os_type, os_version):
        type_version = self.type_version(os_type, os_version)
        user_data_template = open(
            config['openstack']['user-data'][type_version]).read()
        user_data = user_data_template.format(
            up=self.up_string)
        open(self.user_data, 'w').write(user_data)

    def net_id(self):
        network = json.loads(self.run("openstack network show -f json " +
                                      self.openstack['network']))

        def get_id(field):
            return field['Field'] == 'id'
        return filter(get_id, network)[0]['Value']

    def type_version(self, os_type, os_version):
        return os_type + '-' + os_version

    def image(self, os_type, os_version):
        type_version = self.type_version(os_type, os_version)
        return self.openstack['images'][type_version]

    def run(self, command):
        openrc = ". " + self.openstack['openrc.sh'] + " && "
        return misc.sh(openrc + command)

    def cloud_init_wait(self):
        log.debug('cloud_init_wait')
        with safe_while(sleep=600, tries=100,
                        action="cloud_init_wait " + self.name) as proceed:
            success = False
            all_done = ("grep '" + self.up_string + "' " +
                        "/var/log/cloud-init.log")
            while proceed():
                client = paramiko.SSHClient()
                try:
                    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    client.connect(self.name,
                                   key_filename=config['openstack']['ssh-key'],
                                   timeout=5)
                except Exception as e:
                    client.close()
                    if 'Unknown server' in str(e):
                        time.sleep(5)
                        continue
                    else:
                        raise e
                log.debug('cloud_init_wait ' + all_done)
                stdin, stdout, stderr = client.exec_command(all_done)
                stdout.channel.settimeout(5)
                try:
                    out = stdout.read()
                    log.debug('cloud_init_wait stdout ' + all_done + ' ' + out)
                except socket.timeout as e:
                    client.close()
                    continue
                log.debug('cloud_init_wait stderr ' + all_done +
                          ' ' + stderr.read())
                if stdout.channel.recv_exit_status() == 0:
                    success = True
                client.close()
                if success:
                    break
            return success

    def flavor(self):
        """
        Return the smallest flavor that satisfies the desired size.
        """
        desired = config['openstack']['default-size']
        flavors_string = self.run("openstack flavor list -f json")
        flavors = json.loads(flavors_string)
        found = []
        for flavor in flavors:
            if (flavor['RAM'] >= desired['ram'] and
                    flavor['VCPUs'] >= desired['cpus'] and
                    flavor['Disk'] >= desired['disk-size']):
                found.append(flavor)
        if not found:
            log.error("openstack flavor list: " + flavors_string + " " +
                      " does not contain a flavor in which the desired " +
                      str(desired) + " can fit")
            return None

        def sort_flavor(a, b):
            return (a['VCPUs'] - b['VCPUs'] or
                    a['RAM'] - b['RAM'] or
                    a['Disk'] - b['Disk'])
        return sorted(found, cmp=sort_flavor)[0]['Name']

    def get_or_create_volumes(self):
        ids = []
        volumes = config['openstack']['default-volumes']
        for i in range(volumes['count']):
            name = self.name + '-' + str(i)
            try:
                volume = self.run("openstack volume show -f json " + name)
            except subprocess.CalledProcessError as e:
                if 'No volume with a name or ID' not in e.output:
                    raise e
                volume = self.run("openstack volume create -f json " +
                                  self.openstack['volume-create'] + " " +
                                  " --size " + str(volumes['size']) + " " +
                                  name
                                  )
                # wait for the volume to be available ( no --wait )
            def get_id(field):
                return field['Field'] == 'id'
            ids.append(filter(get_id, json.loads(volume))[0]['Value'])
        return ids

    def device_mapping(self):
        ids = self.get_or_create_volumes()
        mapping = ""
        letter = 'b'
        i = 0
        for id in ids:
            dev = "/dev/vd" + chr(ord(letter) + i)
            i += 1
            mapping += ("--block-device-mapping " + dev + "=" +
                        id +
                        " ")
        return mapping

    def create(self, os_type, os_version):
        self.destroy()
        log.debug('OpenStack:create')
        self.init_user_data(os_type, os_version)
        image = self.image(os_type, os_version)
        net_id = self.net_id()
        flavor = self.flavor()
        if not flavor:
            return False
        ip = socket.gethostbyname(self.name)
        device_mapping = self.device_mapping()
        if not self.run("openstack server create " +
                        self.openstack.get('server-create', '') + " " +
                        str(device_mapping) +
                        "--image " + str(image) + " " +
                        "--flavor " + str(flavor) + " " +
                        "--key-name teuthology " +
                        "--user-data " + str(self.user_data) + " " +
                        "--nic net-id=" + str(net_id) + "," +
                        "v4-fixed-ip=" + str(ip) + " " +
                        "--wait " +
                        self.name):
            return False
        if not misc.ssh_keyscan_wait(self.name):
            self.destroy()
            return False
        if not self.cloud_init_wait():
            self.destroy()
            return False
        return True

    def exists(self):
        try:
            self.run("openstack server show -f json " + self.name)
        except subprocess.CalledProcessError as e:
            if 'No server with a name or ID' not in e.output:
                raise e
            return False
        return True

    def destroy(self):
        log.debug('OpenStack:destroy')
        if not self.exists():
            return True
        self.run("openstack server delete " + self.name)
        with safe_while(sleep=60, tries=20,
                        action="destroy " + self.name) as proceed:
            success = False
            while proceed():
                if not self.exists():
                    success = True
                    break
            return success


def create_if_vm(ctx, machine_name, _downburst=None):
    """
    Use downburst to create a virtual machine

    :param _downburst: Only used for unit testing.
    """
    if _downburst:
        status_info = _downburst.status
    else:
        status_info = misc.get_status(machine_name)
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
        status_info = misc.get_status(machine_name)
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
