"""
Support for paramiko remote objects.
"""

import teuthology.lock.query
import teuthology.lock.util
from teuthology.contextutil import safe_while
from teuthology.orchestra import run
from teuthology.orchestra import connection
from teuthology.orchestra import console
from teuthology.orchestra.opsys import OS
import teuthology.provision
from teuthology import misc
from teuthology.exceptions import CommandFailedError, UnitTestError
from teuthology.util.scanner import UnitTestScanner
from teuthology.misc import host_shortname
import errno
import re
import logging
from io import BytesIO
from io import StringIO
import os
import pwd
import tempfile
import netaddr

log = logging.getLogger(__name__)


class RemoteShell(object):
    """
    Contains methods to run miscellaneous shell commands on remote machines.

    These methods were originally part of orchestra.remote.Remote. The reason
    for moving these methods from Remote is that applications that use
    teuthology for testing usually have programs that can run tests locally on
    a single node machine for development work (for example, vstart_runner.py
    in case of Ceph). These programs can import and reuse these methods
    without having to deal SSH stuff. In short, this class serves a shared
    interface.

    To use these methods, inherit the class here and implement "run()" method in
    the subclass.
    """

    def remove(self, path):
        self.run(args=['rm', '-fr', path])

    def mkdtemp(self, suffix=None, parentdir=None):
        """
        Create a temporary directory on remote machine and return it's path.
        """
        args = ['mktemp', '-d']

        if suffix:
            args.append('--suffix=%s' % suffix)
        if parentdir:
            args.append('--tmpdir=%s' % parentdir)

        return self.sh(args).strip()

    def mktemp(self, suffix=None, parentdir=None, data=None):
        """
        Make a remote temporary file.

        :param suffix:      suffix for the temporary file
        :param parentdir:   parent dir where temp file should be created
        :param data:        write data to the file if provided

        Returns: the path of the temp file created.
        """
        args = ['mktemp']
        if suffix:
            args.append('--suffix=%s' % suffix)
        if parentdir:
            args.append('--tmpdir=%s' % parentdir)

        path = self.sh(args).strip()

        if data:
            self.write_file(path=path, data=data)

        return path

    def sh(self, script, **kwargs):
        """
        Shortcut for run method.

        Usage:
            my_name = remote.sh('whoami')
            remote_date = remote.sh('date')
        """
        if 'stdout' not in kwargs:
            kwargs['stdout'] = BytesIO()
        if 'args' not in kwargs:
            kwargs['args'] = script
        proc = self.run(**kwargs)
        out = proc.stdout.getvalue()
        if isinstance(out, bytes):
            return out.decode()
        else:
            return out

    def sh_file(self, script, label="script", sudo=False, **kwargs):
        """
        Run shell script after copying its contents to a remote file

        :param script:  string with script text, or file object
        :param sudo:    run command with sudo if True,
                        run as user name if string value (defaults to False)
        :param label:   string value which will be part of file name
        Returns: stdout
        """
        ftempl = '/tmp/teuthology-remote-$(date +%Y%m%d%H%M%S)-{}-XXXX'\
                 .format(label)
        script_file = self.sh("mktemp %s" % ftempl).strip()
        self.sh("cat - | tee {script} ; chmod a+rx {script}"\
            .format(script=script_file), stdin=script)
        if sudo:
            if isinstance(sudo, str):
                command="sudo -u %s %s" % (sudo, script_file)
            else:
                command="sudo %s" % script_file
        else:
            command="%s" % script_file

        return self.sh(command, **kwargs)

    def chmod(self, file_path, permissions):
        """
        As super-user, set permissions on the remote file specified.
        """
        args = [
            'sudo',
            'chmod',
            permissions,
            file_path,
            ]
        self.run(
            args=args,
            )

    def chcon(self, file_path, context):
        """
        Set the SELinux context of a given file.

        VMs and non-RPM-based hosts will skip this operation because ours
        currently have SELinux disabled.

        :param file_path: The path to the file
        :param context:   The SELinux context to be used
        """
        if self.os.package_type != 'rpm' or \
                self.os.name in ['opensuse', 'sle']:
            return
        if teuthology.lock.query.is_vm(self.shortname):
            return
        self.run(args="sudo chcon {con} {path}".format(
            con=context, path=file_path))

    def copy_file(self, src, dst, sudo=False, mode=None, owner=None,
                                              mkdir=False, append=False):
        """
        Copy data to remote file

        :param src:     source file path on remote host
        :param dst:     destination file path on remote host
        :param sudo:    use sudo to write file, defaults False
        :param mode:    set file mode bits if provided
        :param owner:   set file owner if provided
        :param mkdir:   ensure the destination directory exists, defaults
                        False
        :param append:  append data to the file, defaults False
        """
        dd = 'sudo dd' if sudo else 'dd'
        args = dd + ' if=' + src + ' of=' + dst
        if append:
            args += ' conv=notrunc oflag=append'
        if mkdir:
            mkdirp = 'sudo mkdir -p' if sudo else 'mkdir -p'
            dirpath = os.path.dirname(dst)
            if dirpath:
                args = mkdirp + ' ' + dirpath + '\n' + args
        if mode:
            chmod = 'sudo chmod' if sudo else 'chmod'
            args += '\n' + chmod + ' ' + mode + ' ' + dst
        if owner:
            chown = 'sudo chown' if sudo else 'chown'
            args += '\n' + chown + ' ' + owner + ' ' + dst
        args = 'set -ex' + '\n' + args
        self.run(args=args)

    def move_file(self, src, dst, sudo=False, mode=None, owner=None,
                                              mkdir=False):
        """
        Move data to remote file

        :param src:     source file path on remote host
        :param dst:     destination file path on remote host
        :param sudo:    use sudo to write file, defaults False
        :param mode:    set file mode bits if provided
        :param owner:   set file owner if provided
        :param mkdir:   ensure the destination directory exists, defaults
                        False
        """
        mv = 'sudo mv' if sudo else 'mv'
        args = mv + ' ' + src + ' ' + dst
        if mkdir:
            mkdirp = 'sudo mkdir -p' if sudo else 'mkdir -p'
            dirpath = os.path.dirname(dst)
            if dirpath:
                args = mkdirp + ' ' + dirpath + '\n' + args
        if mode:
            chmod = 'sudo chmod' if sudo else 'chmod'
            args += ' && ' + chmod + ' ' + mode + ' ' + dst
        if owner:
            chown = 'sudo chown' if sudo else 'chown'
            args += ' && ' + chown + ' ' + owner + ' ' + dst
        self.run(args=args)

    def read_file(self, path, sudo=False, stdout=None,
                              offset=0, length=0):
        """
        Read data from remote file

        :param path:    file path on remote host
        :param sudo:    use sudo to read the file, defaults False
        :param stdout:  output object, defaults to io.BytesIO()
        :param offset:  number of bytes to skip from the file
        :param length:  number of bytes to read from the file

        :raises: :class:`FileNotFoundError`: there is no such file by the path
        :raises: :class:`RuntimeError`: unexpected error occurred

        :returns: the file contents in bytes, if stdout is `io.BytesIO`, by
                  default
        :returns: the file contents in str, if stdout is `io.StringIO`
        """
        dd = 'sudo dd' if sudo else 'dd'
        args = dd + ' if=' + path + ' of=/dev/stdout'
        iflags=[]
        # we have to set defaults here instead of the method's signature,
        # because python is reusing the object from call to call
        stdout = stdout or BytesIO()
        if offset:
            args += ' skip=' + str(offset)
            iflags += 'skip_bytes'
        if length:
            args += ' count=' + str(length)
            iflags += 'count_bytes'
        if iflags:
            args += ' iflag=' + ','.join(iflags)
        args = 'set -ex' + '\n' + args
        proc = self.run(args=args, stdout=stdout, stderr=StringIO(),
                        check_status=False, quiet=True)
        if proc.returncode:
            if 'No such file or directory' in proc.stderr.getvalue():
                raise FileNotFoundError(errno.ENOENT,
                        f"Cannot find file on the remote '{self.name}'", path)
            else:
                raise RuntimeError("Unexpected error occurred while trying to "
                        f"read '{path}' file on the remote '{self.name}'")

        return proc.stdout.getvalue()


    def write_file(self, path, data, sudo=False, mode=None, owner=None,
                                     mkdir=False, append=False, bs=None,
                                     offset=None, sync=False):
        """
        Write data to remote file

        The data written in 512-byte blocks, provide `bs` to use bigger blocks.

        :param path:    file path on remote host
        :param data:    str, binary or fileobj to be written
        :param sudo:    use sudo to write file, defaults False
        :param mode:    set file mode bits if provided
        :param owner:   set file owner if provided
        :param mkdir:   preliminary create the file directory, defaults False
        :param append:  append data to the file, defaults False
        :param bs:      write up to N bytes at a time if provided, default is 512 in `dd`
        :param offset:  number of bs blocks to seek to in file, defaults 0
        :param sync:    sync file after write is complete if provided
        """
        dd = 'sudo dd' if sudo else 'dd'
        args = dd + ' of=' + path
        if append:
            args += ' conv=notrunc oflag=append'
        if bs:
            args += ' bs=' + str(bs)
        if offset:
            args += ' seek=' + str(offset)
        if sync:
            args += ' conv=sync'
        if mkdir:
            mkdirp = 'sudo mkdir -p' if sudo else 'mkdir -p'
            dirpath = os.path.dirname(path)
            if dirpath:
                args = mkdirp + ' ' + dirpath + '\n' + args
        if mode:
            chmod = 'sudo chmod' if sudo else 'chmod'
            args += '\n' + chmod + ' ' + mode + ' ' + path
        if owner:
            chown = 'sudo chown' if sudo else 'chown'
            args += '\n' + chown + ' ' + owner + ' ' + path
        args = 'set -ex' + '\n' + args
        self.run(args=args, stdin=data, quiet=True)

    def sudo_write_file(self, path, data, **kwargs):
        """
        Write data to remote file with sudo, for more info see `write_file()`.
        """
        self.write_file(path, data, sudo=True, **kwargs)

    def is_mounted(self, path):
        """
        Check if the given path is mounted on the remote machine.

        This method checks the contents of "/proc/self/mounts" instead of
        using "mount" or "findmnt" command since these commands hang when a
        CephFS client is blocked and its mount point on the remote machine
        is left unhandled/unmounted.

        :param path: path on remote host
        """
        # XXX: matching newline too is crucial so that "/mnt" does not match
        # "/mnt/cephfs" if it's present in the output.
        return f'{path}\n' in self.sh("cat /proc/self/mounts | awk '{print $2}'")

    @property
    def os(self):
        if not hasattr(self, '_os'):
            try:
                os_release = self.sh('cat /etc/os-release').strip()
                self._os = OS.from_os_release(os_release)
                return self._os
            except CommandFailedError:
                pass

            lsb_release = self.sh('lsb_release -a').strip()
            self._os = OS.from_lsb_release(lsb_release)
        return self._os

    @property
    def arch(self):
        if not hasattr(self, '_arch'):
            self._arch = self.sh('uname -m').strip()
        return self._arch


class Remote(RemoteShell):
    """
    A connection to a remote host.

    This is a higher-level wrapper around Paramiko's `SSHClient`.
    """

    # for unit tests to hook into
    _runner = staticmethod(run.run)
    _reimage_types = None

    def __init__(self, name, ssh=None, shortname=None, console=None,
                 host_key=None, keep_alive=True):
        self.name = name
        if '@' in name:
            (self.user, hostname) = name.split('@')
            # Temporary workaround for 'hostname --fqdn' not working on some
            # machines
            self._hostname = hostname
        else:
            # os.getlogin() doesn't work on non-login shells. The following
            # should work on any unix system
            self.user = pwd.getpwuid(os.getuid()).pw_name
            hostname = name
        self._shortname = shortname or host_shortname(hostname)
        self._host_key = host_key
        self.keep_alive = keep_alive
        self._console = console
        self.ssh = ssh

        if self._reimage_types is None:
            Remote._reimage_types = teuthology.provision.get_reimage_types()

    def connect(self, timeout=None, create_key=None, context='connect'):
        args = dict(user_at_host=self.name, host_key=self._host_key,
                    keep_alive=self.keep_alive, _create_key=create_key)
        if context == 'reconnect':
            # The reason for the 'context' workaround is not very
            # clear from the technical side.
            # I'll get "[Errno 98] Address already in use" altough
            # there are no open tcp(ssh) connections.
            # When connecting without keepalive, host_key and _create_key 
            # set, it will proceed.
            args = dict(user_at_host=self.name, _create_key=False, host_key=None)
        if timeout:
            args['timeout'] = timeout

        self.ssh = connection.connect(**args)
        return self.ssh

    def reconnect(self, timeout=30, socket_timeout=None):
        """
        Attempts to re-establish connection. Returns True for success; False
        for failure.
        """
        if self.ssh is not None:
            self.ssh.close()
        if not timeout:
            return self._reconnect(timeout=socket_timeout)
        action = "reconnect to {self.shortname}"
        with safe_while(action=action, timeout=timeout, increment=3, _raise=False) as proceed:
            success = False
            while proceed():
                success = self._reconnect(timeout=socket_timeout)
                if success:
                    log.info(f"Successfully reconnected to host '{self.name}'")
                    return success
            return success

    def _reconnect(self, timeout=None):
        log.info(f"Trying to reconnect to host '{self.name}'")
        try:
            self.connect(timeout=timeout, context='reconnect')
            return self.is_online
        except Exception as e:
            log.debug(e)
            return False

    @property
    def ip_address(self):
        return self.ssh.get_transport().getpeername()[0]

    @property
    def interface(self):
        """
        The interface used by the current SSH connection
        """
        if not hasattr(self, '_interface'):
            self._set_iface_and_cidr()
        return self._interface

    @property
    def cidr(self):
        """
        The network (in CIDR notation) used by the remote's SSH connection
        """
        if not hasattr(self, '_cidr'):
            self._set_iface_and_cidr()
        return self._cidr

    def _set_iface_and_cidr(self):
        ip_addr_show = self.sh('PATH=/sbin:/usr/sbin ip addr show')
        regexp = 'inet.? %s' % self.ip_address
        for line in ip_addr_show.split('\n'):
            line = line.strip()
            if re.match(regexp, line):
                items = line.split()
                self._interface = items[-1]
                self._cidr = str(netaddr.IPNetwork(items[1]).cidr)
                return
        raise RuntimeError("Could not determine interface/CIDR!")


    def resolve_ip(self, name=None, ipv='4') -> str:
        """
        Resolve IP address of the remote host via remote host

        Because remote object maybe behind bastion host we need
        the remote host address resolvable from remote side.
        So in order to the ip address we just call `host` remotely
        and parse output like:
            'smithi001.front.sepia.ceph.com has address 172.21.15.1\n'

        :param name:    hostname to resolve, by defaults remote host itself.
        :param ipv:     the IP version, 4 or 6, defaults to 4.

        :raises:    :class:`Exception`: when the hostname cannot be resolved.
        :raises:    :class:`ValueError`: when the ipv argument mismatch 4 or 6.

        :returns:   str object, the ip addres of the remote host.
        """
        hostname = name or self.hostname
        version = str(ipv)
        if version in ['4', '6']:
            remote_host_ip = self.sh(f'host -{ipv} {hostname}')
        else:
            raise ValueError(f'Unknown IP version {ipv}, expected 4 or 6')
        # `host -4` or `host -6` may have multiline output: a host can have
        # several address; thus try and find the first suitable
        for info in remote_host_ip.split("\n"):
            if version == '4' and 'has address' in info:
                (host, ip) = info.strip().split(' has address ')
                if hostname in host:
                    return ip
            elif version == '6' and 'has IPv6 address' in info:
                (host, ip) = info.strip().split(' has IPv6 address ')
                if hostname in host:
                    return ip
        else:
            raise Exception(f'Cannot get IPv{ipv} address for the host "{hostname}" via remote "{self.hostname}"')


    @property
    def hostname(self):
        if not hasattr(self, '_hostname'):
            self._hostname = self.sh('hostname --fqdn').strip()
        return self._hostname

    @property
    def machine_type(self):
        if not getattr(self, '_machine_type', None):
            remote_info = teuthology.lock.query.get_status(self.hostname)
            if not remote_info:
                return None
            self._machine_type = remote_info.get("machine_type", None)
        return self._machine_type

    @property
    def is_reimageable(self):
        return self.machine_type in self._reimage_types

    @property
    def shortname(self):
        if self._shortname is None:
            self._shortname = host_shortname(self.hostname)
        return self._shortname

    @property
    def is_online(self):
        if self.ssh is None:
            return False
        if self.ssh.get_transport() is None:
            return False
        try:
            self.run(args="true")
        except Exception:
            return False
        return self.ssh.get_transport().is_active()

    def ensure_online(self):
        if self.is_online:
            return
        self.connect()
        if not self.is_online:
            raise ConnectionError(f'Failed to connect to {self.shortname}')

    @property
    def system_type(self):
        """
        System type decorator
        """
        return misc.get_system_type(self)

    def __str__(self):
        return self.name

    def __repr__(self):
        return '{classname}(name={name!r})'.format(
            classname=self.__class__.__name__,
            name=self.name,
            )

    def run(self, **kwargs):
        """
        This calls `orchestra.run.run` with our SSH client.

        TODO refactor to move run.run here?
        """
        if not self.ssh or \
           not self.ssh.get_transport() or \
           not self.ssh.get_transport().is_active():
            if not self.reconnect():
                raise ConnectionError(f'Failed to reconnect to {self.shortname}')
        r = self._runner(client=self.ssh, name=self.shortname, **kwargs)
        r.remote = self
        return r

    def run_unit_test(self, xml_path_regex, output_yaml, **kwargs):
        try:
            r = self.run(**kwargs)
        except CommandFailedError as exc:
            if xml_path_regex:
                error_msg = UnitTestScanner(remote=self).scan_and_write(xml_path_regex, output_yaml)
                if error_msg:
                    raise UnitTestError(
                        exitstatus=exc.exitstatus, node=exc.node, 
                        label=exc.label, message=error_msg
                    )
            raise exc
        return r

    def _sftp_put_file(self, local_path, remote_path):
        """
        Use the paramiko.SFTPClient to put a file. Returns the remote filename.
        """
        sftp = self.ssh.open_sftp()
        sftp.put(local_path, remote_path)
        return

    def _sftp_get_file(self, remote_path, local_path):
        """
        Use the paramiko.SFTPClient to get a file. Returns the local filename.
        """
        file_size = self._format_size(
            self._sftp_get_size(remote_path)
        ).strip()
        log.debug("{}:{} is {}".format(self.shortname, remote_path, file_size))
        sftp = self.ssh.open_sftp()
        sftp.get(remote_path, local_path)
        return local_path

    def _sftp_open_file(self, remote_path, mode=None):
        """
        Use the paramiko.SFTPClient to open a file. Returns a
        paramiko.SFTPFile object.
        """
        sftp = self.ssh.open_sftp()
        if mode:
            return sftp.open(remote_path, mode)
        return sftp.open(remote_path)

    def _sftp_get_size(self, remote_path):
        """
        Via _sftp_open_file, return the filesize in bytes
        """
        with self._sftp_open_file(remote_path) as f:
            return f.stat().st_size

    @staticmethod
    def _format_size(file_size):
        """
        Given a file_size in bytes, returns a human-readable representation.
        """
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if abs(file_size) < 1024.0:
                break
            file_size = file_size / 1024.0
        return "{:3.0f}{}".format(file_size, unit)

    def put_file(self, path, dest_path, sudo=False):
        """
        Copy a local filename to a remote file
        """
        if sudo:
            raise NotImplementedError("sudo not supported")

        self._sftp_put_file(path, dest_path)
        return

    def get_file(self, path, sudo=False, dest_dir='/tmp'):
        """
        Fetch a remote file, and return its local filename.

        :param sudo:     Use sudo on the remote end to read a file that
                         requires it. Defaults to False.
        :param dest_dir: Store the file in this directory. If it is /tmp,
                         generate a unique filename; if not, use the original
                         filename.
        :returns:        The path to the local file
        """
        if not os.path.isdir(dest_dir):
            raise IOError("{dir} is not a directory".format(dir=dest_dir))

        if sudo:
            orig_path = path
            path = self.mktemp()
            args = [
                'sudo',
                'cp',
                orig_path,
                path,
                ]
            self.run(args=args)
            self.chmod(path, '0666')

        if dest_dir == '/tmp':
            # If we're storing in /tmp, generate a unique filename
            (fd, local_path) = tempfile.mkstemp(dir=dest_dir)
            os.close(fd)
        else:
            # If we are storing somewhere other than /tmp, use the original
            # filename
            local_path = os.path.join(dest_dir, path.split(os.path.sep)[-1])

        self._sftp_get_file(path, local_path)
        if sudo:
            self.remove(path)
        return local_path

    def get_tar(self, path, to_path, sudo=False, compress=True):
        """
        Tar a remote directory and copy it locally
        """
        remote_temp_path = self.mktemp()
        args = []
        if sudo:
            args.append('sudo')
        args.extend([
            'tar',
            'cz' if compress else 'c',
            '-f', '-',
            '-C', path,
            '--',
            '.',
            run.Raw('>'), remote_temp_path
            ])
        self.run(args=args)
        if sudo:
            self.chmod(remote_temp_path, '0666')
        self._sftp_get_file(remote_temp_path, to_path)
        self.remove(remote_temp_path)

    def get_tar_stream(self, path, sudo=False, compress=True):
        """
        Tar-compress a remote directory and return the RemoteProcess
        for streaming
        """
        args = []
        if sudo:
            args.append('sudo')
        args.extend([
            'tar',
            'cz' if compress else 'c',
            '-f', '-',
            '-C', path,
            '--',
            '.',
            ])
        return self.run(args=args, wait=False, stdout=run.PIPE)

    @property
    def host_key(self):
        if not self._host_key:
            trans = self.ssh.get_transport()
            key = trans.get_remote_server_key()
            self._host_key = ' '.join((key.get_name(), key.get_base64()))
        return self._host_key

    @property
    def inventory_info(self):
        node = dict()
        node['name'] = self.hostname
        node['user'] = self.user
        node['arch'] = self.arch
        node['os_type'] = self.os.name
        node['os_version'] = '.'.join(self.os.version.split('.')[:2])
        node['ssh_pub_key'] = self.host_key
        node['up'] = True
        return node

    @property
    def console(self):
        if not self._console:
            self._console = getRemoteConsole(self.name)
        return self._console

    @property
    def is_vm(self):
        if not hasattr(self, '_is_vm'):
            self._is_vm = teuthology.lock.query.is_vm(self.name)
        return self._is_vm

    @property
    def is_container(self):
        if not hasattr(self, '_is_container'):
            self._is_container = not bool(self.run(
                args="test -f /run/.containerenv -o -f /.dockerenv",
                check_status=False,
            ).returncode)
        return self._is_container

    @property
    def init_system(self):
        """
        Which init system does the remote use?

        :returns: 'systemd' or None
        """
        if not hasattr(self, '_init_system'):
            self._init_system = None
            proc = self.run(
                args=['which', 'systemctl'],
                check_status=False,
            )
            if proc.returncode == 0:
                self._init_system = 'systemd'
        return self._init_system

    def __del__(self):
        if self.ssh is not None:
            self.ssh.close()


def getRemoteConsole(name, ipmiuser=None, ipmipass=None, ipmidomain=None,
                     timeout=60):
    """
    Return either VirtualConsole or PhysicalConsole depending on name.
    """
    if teuthology.lock.query.is_vm(name):
        try:
            return console.VirtualConsole(name)
        except Exception:
            return None
    return console.PhysicalConsole(
        name, ipmiuser, ipmipass, ipmidomain, timeout)
