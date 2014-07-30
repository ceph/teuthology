
from StringIO import StringIO
import json
import time
import os
import logging

from teuthology import misc
from ...orchestra import run
from teuthology.orchestra.run import CommandFailedError
from teuthology.task.cephfs.mount import CephFSMount

log = logging.getLogger(__name__)


class FuseMount(CephFSMount):
    def __init__(self, client_config, test_dir, client_id, client_remote):
        super(FuseMount, self).__init__(test_dir, client_id, client_remote)

        self.client_config = client_config if client_config else {}
        self.fuse_daemon = None

    def mount(self):
        log.info("Client client.%s config is %s" % (self.client_id, self.client_config))

        daemon_signal = 'kill'
        if self.client_config.get('coverage') or self.client_config.get('valgrind') is not None:
            daemon_signal = 'term'

        mnt = os.path.join(self.test_dir, 'mnt.{id}'.format(id=self.client_id))
        log.info('Mounting ceph-fuse client.{id} at {remote} {mnt}...'.format(
            id=self.client_id, remote=self.client_remote, mnt=mnt))

        self.client_remote.run(
            args=[
                'mkdir',
                '--',
                mnt,
            ],
        )

        run_cmd = [
            'sudo',
            'adjust-ulimits',
            'ceph-coverage',
            '{tdir}/archive/coverage'.format(tdir=self.test_dir),
            'daemon-helper',
            daemon_signal,
        ]
        run_cmd_tail = [
            'ceph-fuse',
            '-f',
            '--name', 'client.{id}'.format(id=self.client_id),
            # TODO ceph-fuse doesn't understand dash dash '--',
            mnt,
        ]

        if self.client_config.get('valgrind') is not None:
            run_cmd = misc.get_valgrind_args(
                self.test_dir,
                'client.{id}'.format(id=self.client_id),
                run_cmd,
                self.client_config.get('valgrind'),
            )

        run_cmd.extend(run_cmd_tail)

        proc = self.client_remote.run(
            args=run_cmd,
            logger=log.getChild('ceph-fuse.{id}'.format(id=self.client_id)),
            stdin=run.PIPE,
            wait=False,
        )
        self.fuse_daemon = proc

    def is_mounted(self):
        try:
            proc = self.client_remote.run(
                args=[
                    'stat',
                    '--file-system',
                    '--printf=%T\n',
                    '--',
                    self.mountpoint,
                ],
                stdout=StringIO(),
            )
        except CommandFailedError:
            # This happens if the mount directory doesn't exist
            return False

        fstype = proc.stdout.getvalue().rstrip('\n')
        if fstype == 'fuseblk':
            log.info('ceph-fuse is mounted on %s', self.mountpoint)
            return True
        else:
            log.debug('ceph-fuse not mounted, got fs type {fstype!r}'.format(
                fstype=fstype))

    def wait_until_mounted(self):
        """
        Check to make sure that fuse is mounted on mountpoint.  If not,
        sleep for 5 seconds and check again.
        """

        while not self.is_mounted():
            # Even if it's not mounted, it should at least
            # be running: catch simple failures where it has terminated.
            assert not self.fuse_daemon.poll()

            time.sleep(5)

        # Now that we're mounted, set permissions so that the rest of the test will have
        # unrestricted access to the filesystem mount.
        self.client_remote.run(
            args=['sudo', 'chmod', '1777', '{tdir}/mnt.{id}'.format(tdir=self.test_dir, id=self.client_id)], )

    def umount(self):
        try:
            self.client_remote.run(
                args=[
                    'sudo',
                    'fusermount',
                    '-u',
                    self.mountpoint,
                ],
            )
        except run.CommandFailedError:
            # FIXME: this will clobber all FUSE mounts, not just this one

            log.info('Failed to unmount ceph-fuse on {name}, aborting...'.format(name=self.client_remote.name))
            # abort the fuse mount, killing all hung processes
            self.client_remote.run(
                args=[
                    'if', 'test', '-e', '/sys/fs/fuse/connections/*/abort',
                    run.Raw(';'), 'then',
                    'echo',
                    '1',
                    run.Raw('>'),
                    run.Raw('/sys/fs/fuse/connections/*/abort'),
                    run.Raw(';'), 'fi',
                ],
            )
            # make sure its unmounted
            self.client_remote.run(
                args=[
                    'sudo',
                    'umount',
                    '-l',
                    '-f',
                    self.mountpoint,
                ],
            )

    def umount_wait(self, force=False):
        """
        :param force: Complete even if the MDS is offline
        """
        self.umount()
        if force:
            self.fuse_daemon.stdin.close()
        try:
            self.fuse_daemon.wait()
        except CommandFailedError:
            pass
        self.cleanup()

    def cleanup(self):
        """
        Remove the mount point.

        Prerequisite: the client is not mounted.
        """
        self.client_remote.run(
            args=[
                'rmdir',
                '--',
                self.mountpoint,
            ],
        )

    def kill(self):
        """
        Terminate the client without removing the mount point.
        """
        self.fuse_daemon.stdin.close()
        try:
            self.fuse_daemon.wait()
        except CommandFailedError:
            pass

    def kill_cleanup(self):
        """
        Follow up ``kill`` to get to a clean unmounted state.
        """
        self.umount()
        self.cleanup()

    def teardown(self):
        """
        Whatever the state of the mount, get it gone.
        """
        super(FuseMount, self).teardown()

        self.umount()
        if not self.fuse_daemon.finished:
            self.fuse_daemon.stdin.close()
            try:
                self.fuse_daemon.wait()
            except CommandFailedError:
                pass

        # Indiscriminate, unlike the touchier cleanup()
        self.client_remote.run(
            args=[
                'rm',
                '-rf',
                self.mountpoint,
            ],
        )

    # FIXME: bad naming scheme to call this client_id and also have the
    # 'client_id' attr which is something completely different.  This
    # is what a MonSession calls global_id.
    def get_client_id(self):
        """
        Look up the CephFS client ID for this mount
        """

        pyscript = """
import glob
import re
import os
import subprocess

def find_socket(client_name):
        files = glob.glob("/var/run/ceph/ceph-{{client_name}}.*.asok".format(client_name=client_name))
        for f in files:
                pid = re.match(".*\.(\d+)\.asok$", f).group(1)
                if os.path.exists("/proc/{{0}}".format(pid)):
                        return f
        raise RuntimeError("Client socket {{0}} not found".format(client_name))

print find_socket("{client_name}")
""".format(client_name="client.{0}".format(self.client_id))

        # Find the admin socket
        p = self.client_remote.run(args=[
            'python', '-c', pyscript
        ], stdout=StringIO())
        asok_path = p.stdout.getvalue().strip()
        log.info("Found client admin socket at {0}".format(asok_path))

        # Query client ID from admin socket
        p = self.client_remote.run(
            args=['sudo', 'ceph', '--admin-daemon', asok_path, 'mds_sessions'],
            stdout=StringIO())
        return json.loads(p.stdout.getvalue())['id']
