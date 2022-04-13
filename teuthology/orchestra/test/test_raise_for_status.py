from io import BytesIO

import paramiko

from mock import MagicMock
from pytest import raises

from teuthology.orchestra import run
from teuthology.exceptions import (CommandCrashedError, CommandFailedError,
                                   ConnectionLostError)

class TestRaiseForStatus(object):
    def setup(self):
        self.m_channel = MagicMock(spec=paramiko.Channel)()
        class M_ChannelFile(BytesIO):
            channel = MagicMock(spec=paramiko.Channel)()

        self.m_channelfile = M_ChannelFile
        self.m_stdin_buf = self.m_channelfile()
        self.m_stdout_buf = self.m_channelfile()
        self.m_stderr_buf = self.m_channelfile()
        self.m_ssh = MagicMock()
        self.m_ssh.exec_command.return_value = (
            self.m_stdin_buf,
            self.m_stdout_buf,
            self.m_stderr_buf,
        )
        self.m_transport = MagicMock()
        self.m_transport.getpeername.return_value = ('name', 22)
        self.m_ssh.get_transport.return_value = self.m_transport
        self.proc = run.RemoteProcess(
            client=self.m_ssh,
            args=['foo'],
        )
        self.proc._stdout_buf = self.m_stdout_buf

    def test_status_lost(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = -1
        self.m_transport.is_active.return_value = False
        with raises(ConnectionLostError) as exc:
            self.proc._raise_for_status()
        assert str(exc.value) == "SSH connection to name was lost: 'foo'"
    
    def test_status_crash(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = -1
        with raises(CommandCrashedError) as exc:
            self.proc._raise_for_status()
        assert str(exc.value) == "Command crashed: 'foo'"

    def test_status_crash_nocheck(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = -1
        self.proc.check_status = False
        self.proc._raise_for_status()
        assert self.proc.exitstatus == -1
    
    def test_status_bad(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = 42
        with raises(CommandFailedError) as exc:
            self.proc._raise_for_status()
        assert str(exc.value) == "Command failed on name with status 42: 'foo'"

    def test_status_bad_nocheck(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = 42
        self.proc.check_status = False
        self.proc._raise_for_status()
        assert self.proc.exitstatus == 42
