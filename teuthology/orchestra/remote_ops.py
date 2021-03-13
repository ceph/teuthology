"""
Contains methods to run standard operations (like creating/deleting files) on
remote machines.

These methods were originally part of orchestra.remote.Remote. The reason for
moving these methods from Remote to here is that applications that use
teuthology for testing usually have programs that can run tests locally on a
single node machine for development work (for example, vstart_runner.py in
case of Ceph). These programs can import and reuse these methods without
having to deal SSH stuff.

To use these methods, inherit the class here and implement "run()" method in
the subclass.
"""

from errno import ENOENT as errno_ENOENT
from io import BytesIO
from io import StringIO
from os.path import dirname as os_path_dirname

from teuthology.exceptions import CommandFailedError
from teuthology.lock.query import is_vm
from teuthology.orchestra.opsys import OS


class NonTransferRemoteOps(object):
    """
    This class serves a shared interface for teuthology's orchestra and
    vstart_runner. It contains methods that operate on the given remote
    machine without needing another remote machine.
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

    def mktemp(self, suffix=None, parentdir=None):
        """
        Make a remote temporary file

        Returns: the path of the temp file created.
        """
        args = ['mktemp']

        if suffix:
            args.append('--suffix=%s' % suffix)
        if parentdir:
            args.append('--tmpdir=%s' % parentdir)

        return self.sh(args).strip()

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
        self.sh("cat - | tee {script} ; chmod a+rx {script}"
                .format(script=script_file), stdin=script)
        if sudo:
            if isinstance(sudo, str):
                command = "sudo -u %s %s" % (sudo, script_file)
            else:
                command = "sudo %s" % script_file
        else:
            command = "%s" % script_file

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
        if is_vm(self.shortname):
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
            dirpath = os_path_dirname(dst)
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
            dirpath = os_path_dirname(dst)
            if dirpath:
                args = mkdirp + ' ' + dirpath + '\n' + args
        if mode:
            chmod = 'sudo chmod' if sudo else 'chmod'
            args += ' && ' + chmod + ' ' + mode + ' ' + dst
        if owner:
            chown = 'sudo chown' if sudo else 'chown'
            args += ' && ' + chown + ' ' + owner + ' ' + dst
        self.run(args=args)

    def read_file(self, path, sudo=False, stdout=None, offset=0, length=0):
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
        iflags = []
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
                raise FileNotFoundError(errno_ENOENT, "Cannot find file on "
                                        f"the remote '{self.name}'", path)
            else:
                raise RuntimeError("Unexpected error occurred while trying to "
                                   f"read '{path}' file on the remote "
                                   f"'{self.name}'")

        return proc.stdout.getvalue()

    def write_file(self, path, data, sudo=False, mode=None, owner=None,
                   mkdir=False, append=False):
        """
        Write data to remote file

        :param path:    file path on remote host
        :param data:    str, binary or fileobj to be written
        :param sudo:    use sudo to write file, defaults False
        :param mode:    set file mode bits if provided
        :param owner:   set file owner if provided
        :param mkdir:   preliminary create the file directory, defaults False
        :param append:  append data to the file, defaults False
        """
        dd = 'sudo dd' if sudo else 'dd'
        args = dd + ' of=' + path
        if append:
            args += ' conv=notrunc oflag=append'
        if mkdir:
            mkdirp = 'sudo mkdir -p' if sudo else 'mkdir -p'
            dirpath = os_path_dirname(path)
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
