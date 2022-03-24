from io import BytesIO

from mock import MagicMock, Mock
from pytest import raises

from teuthology.orchestra.run import RemoteProcess
from teuthology.exceptions import (CommandCrashedError, CommandFailedError,
                                   ConnectionLostError)


class TestRaiseForStatus(object):
    def setup(self):
        self.m_transport = MagicMock()
        self.m_transport.getpeername.return_value = ('name', 22)
        self.m_ssh = MagicMock()
        self.m_ssh.get_transport.return_value = self.m_transport
        stdout = BytesIO(b'test_hostname')
        stdout.seek(0)
        self.proc = RemoteProcess(
            client=self.m_ssh,
            args=['foo'],
            )
        self.proc.stdout = stdout
        self.proc._stdout_buf = Mock()

    def test_raise_for_status_failed(self):
        self.proc._stdout_buf.channel.recv_exit_status.return_value = 42
        with raises(CommandFailedError) as exc:
            self.proc._raise_for_status()
        assert self.proc.returncode == 42
        assert str(exc.value) == "Command failed on name with status 42: 'foo'"

    def test_raise_for_status_crashed(self):
        self.proc._stdout_buf.channel.recv_exit_status.return_value = -1
        with raises(CommandCrashedError) as exc:
            self.proc._raise_for_status()
        assert self.proc.returncode == -1
        assert str(exc.value) == "Command crashed: 'foo'"

    def test_raise_for_status_lost(self):
        self.m_transport.is_active.return_value = False
        self.proc._stdout_buf.channel.recv_exit_status.return_value = -1
        with raises(ConnectionLostError) as exc:
            self.proc._raise_for_status()
        assert self.proc.returncode == -1
        assert str(exc.value) == "SSH connection to name was lost: 'foo'"

