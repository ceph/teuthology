from teuthology.orchestra import monkey
monkey.patch_all()

import os
from teuthology.compat import BytesIO
from teuthology.orchestra import connection, remote, run
from teuthology.orchestra.test.util import assert_raises
from teuthology.exceptions import CommandCrashedError, ConnectionLostError

from pytest import skip

HOST = None


class TestIntegration():
    def setup(self):
        try:
            host = os.environ['ORCHESTRA_TEST_HOST']
        except KeyError:
            skip('To run integration tests, set environment ' +
                 'variable ORCHESTRA_TEST_HOST to user@host to use.')
        global HOST
        HOST = host

    def test_crash(self):
        ssh = connection.connect(HOST)
        e = assert_raises(
            CommandCrashedError,
            run.run,
            client=ssh,
            args=['sh', '-c', 'kill -ABRT $$'],
            )
        assert e.command == "sh -c 'kill -ABRT $$'"
        assert str(e) == "Command crashed: \"sh -c 'kill -ABRT $$'\""

    def test_lost(self):
        ssh = connection.connect(HOST)
        e = assert_raises(
            ConnectionLostError,
            run.run,
            client=ssh,
            args=['sh', '-c', 'kill -ABRT $PPID'],
            name=HOST,
            )
        assert e.command == "sh -c 'kill -ABRT $PPID'"
        assert str(e) == \
            "SSH connection to {host} was lost: ".format(host=HOST) + \
            "\"sh -c 'kill -ABRT $PPID'\""

    def test_pipe(self):
        ssh = connection.connect(HOST)
        r = run.run(
            client=ssh,
            args=['cat'],
            stdin=run.PIPE,
            stdout=BytesIO(),
            wait=False,
            )
        assert r.stdout.getvalue() == b''
        r.stdin.write(b'foo\n')
        r.stdin.write(b'bar\n')
        r.stdin.close()

        r.wait()
        got = r.exitstatus
        assert got == 0
        assert r.stdout.getvalue() == b'foo\nbar\n'

    def test_and(self):
        ssh = connection.connect(HOST)
        r = run.run(
            client=ssh,
            args=['true', run.Raw('&&'), 'echo', 'yup'],
            stdout=BytesIO(),
            )
        assert r.stdout.getvalue() == b'yup\n'

    def test_os(self):
        rem = remote.Remote(HOST)
        assert rem.os.name
        assert rem.os.version
