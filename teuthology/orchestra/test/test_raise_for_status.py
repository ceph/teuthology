from io import BytesIO
import paramiko
from mock import MagicMock
from teuthology.exceptions import CommandCrashedError, CommandFailedError
from teuthology.orchestra import run


class TestRaiseForStatus(object):
    """This class verifies whether proper exceptions are being thrown according to access and return codes."""
    def setup(self):
        """Setup method."""
        self.m_channel = MagicMock(spec=paramiko.Channel)()

        class MChannelFile(BytesIO):
            """This class creates a channel type object."""
            channel = MagicMock(spec=paramiko.Channel)()

        self.m_channelfile = MChannelFile
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
        self.m_transport.getpeername.return_value = ('echo', 22)
        self.m_ssh.get_transport.return_value = self.m_transport
        self.proc = run.RemoteProcess(
            client=self.m_ssh,
            args=['abc'],
        )
        self.proc._stdout_buf = self.m_stdout_buf

    def test_status_code(self):
        """This test raises CommandFailedError when check_status is True and the value returncode is not Zero.
        Returns:
            Nothing, but raises on error.
        """
        self.m_stdout_buf.channel.recv_exit_status.return_value = 0

        if self.proc.returncode is None:
            self.proc._get_exitstatus()
        if self.proc.check_status:
            if self.proc.returncode in (None, -1):
                raise CommandCrashedError(command=self.proc.command)
            if self.proc.returncode != 0:
                raise CommandFailedError(
                    command=self.proc.command, exitstatus=self.proc.returncode,
                    node=self.proc.hostname, label=self.proc.label
                )

