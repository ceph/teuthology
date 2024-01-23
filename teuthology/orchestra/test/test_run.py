from io import BytesIO

import paramiko
import pytest
import socket

from mock import MagicMock, patch

from teuthology.orchestra import run
from teuthology.exceptions import (CommandCrashedError, CommandFailedError,
                                   ConnectionLostError)

def set_buffer_contents(buf, contents):
    buf.seek(0)
    if isinstance(contents, bytes):
        buf.write(contents)
    elif isinstance(contents, (list, tuple)):
        buf.writelines(contents)
    elif isinstance(contents, str):
        buf.write(contents.encode())
    else:
        raise TypeError(
            "%s is a %s; should be a byte string, list or tuple" % (
                contents, type(contents)
            )
        )
    buf.seek(0)


class TestRun(object):
    def setup_method(self):
        self.start_patchers()

    def teardown_method(self):
        self.stop_patchers()

    def start_patchers(self):
        self.m_remote_process = MagicMock(wraps=run.RemoteProcess)
        self.patcher_remote_proc = patch(
            'teuthology.orchestra.run.RemoteProcess',
            self.m_remote_process,
        )
        self.m_channel = MagicMock(spec=paramiko.Channel)()
        """
        self.m_channelfile = MagicMock(wraps=paramiko.ChannelFile)
        self.m_stdin_buf = self.m_channelfile(self.m_channel())
        self.m_stdout_buf = self.m_channelfile(self.m_channel())
        self.m_stderr_buf = self.m_channelfile(self.m_channel())
        """
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
        self.patcher_ssh = patch(
            'teuthology.orchestra.connection.paramiko.SSHClient',
            self.m_ssh,
        )
        self.patcher_ssh.start()
        # Tests must start this if they wish to use it
        # self.patcher_remote_proc.start()

    def stop_patchers(self):
        # If this patcher wasn't started, it's ok
        try:
            self.patcher_remote_proc.stop()
        except RuntimeError:
            pass
        self.patcher_ssh.stop()

    @pytest.mark.asyncio
    async def test_exitstatus(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = 0
        proc = await run.run(
            client=self.m_ssh,
            args=['foo', 'bar baz'],
        )
        assert proc.exitstatus == 0

    @pytest.mark.asyncio
    async def test_run_cwd(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = 0
        await run.run(
            client=self.m_ssh,
            args=['foo_bar_baz'],
            cwd='/cwd/test',
        )
        self.m_ssh.exec_command.assert_called_with('(cd /cwd/test && exec foo_bar_baz)')

    @pytest.mark.asyncio
    async def test_capture_stdout(self):
        output = 'foo\nbar'
        set_buffer_contents(self.m_stdout_buf, output)
        self.m_stdout_buf.channel.recv_exit_status.return_value = 0
        stdout = BytesIO()
        proc = await run.run(
            client=self.m_ssh,
            args=['foo', 'bar baz'],
            stdout=stdout,
        )
        assert proc.stdout is stdout
        assert proc.stdout.read().decode() == output
        assert proc.stdout.getvalue().decode() == output

    @pytest.mark.asyncio
    async def test_capture_stderr_newline(self):
        output = 'foo\nbar\n'
        set_buffer_contents(self.m_stderr_buf, output)
        self.m_stderr_buf.channel.recv_exit_status.return_value = 0
        stderr = BytesIO()
        proc = await run.run(
            client=self.m_ssh,
            args=['foo', 'bar baz'],
            stderr=stderr,
        )
        assert proc.stderr is stderr
        assert proc.stderr.read().decode() == output
        assert proc.stderr.getvalue().decode() == output

    @pytest.mark.asyncio
    async def test_status_bad(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = 42
        with pytest.raises(CommandFailedError) as exc:
            await run.run(
                client=self.m_ssh,
                args=['foo'],
            )
        assert str(exc.value) == "Command failed on name with status 42: 'foo'"

    @pytest.mark.asyncio
    async def test_status_bad_nocheck(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = 42
        proc = await run.run(
            client=self.m_ssh,
            args=['foo'],
            check_status=False,
        )
        assert proc.exitstatus == 42

    @pytest.mark.asyncio
    async def test_status_crash(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = -1
        with pytest.raises(CommandCrashedError) as exc:
            await run.run(
                client=self.m_ssh,
                args=['foo'],
            )
        assert str(exc.value) == "Command crashed: 'foo'"

    @pytest.mark.asyncio
    async def test_status_crash_nocheck(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = -1
        proc = await run.run(
            client=self.m_ssh,
            args=['foo'],
            check_status=False,
        )
        assert proc.exitstatus == -1

    @pytest.mark.asyncio
    async def test_status_lost(self):
        m_transport = MagicMock()
        m_transport.getpeername.return_value = ('name', 22)
        m_transport.is_active.return_value = False
        self.m_stdout_buf.channel.recv_exit_status.return_value = -1
        self.m_ssh.get_transport.return_value = m_transport
        with pytest.raises(ConnectionLostError) as exc:
            await run.run(
                client=self.m_ssh,
                args=['foo'],
            )
        assert str(exc.value) == "SSH connection to name was lost: 'foo'"

    @pytest.mark.asyncio
    async def test_status_lost_socket(self):
        m_transport = MagicMock()
        m_transport.getpeername.side_effect = socket.error
        self.m_ssh.get_transport.return_value = m_transport
        with pytest.raises(ConnectionLostError) as exc:
            await run.run(
                client=self.m_ssh,
                args=['foo'],
            )
        assert str(exc.value) == "SSH connection was lost: 'foo'"

    @pytest.mark.asyncio
    async def test_status_lost_nocheck(self):
        m_transport = MagicMock()
        m_transport.getpeername.return_value = ('name', 22)
        m_transport.is_active.return_value = False
        self.m_stdout_buf.channel.recv_exit_status.return_value = -1
        self.m_ssh.get_transport.return_value = m_transport
        proc = await run.run(
            client=self.m_ssh,
            args=['foo'],
            check_status=False,
        )
        assert proc.exitstatus == -1

    @pytest.mark.asyncio
    async def test_status_bad_nowait(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = 42
        proc = await run.run(
            client=self.m_ssh,
            args=['foo'],
            wait=False,
        )
        with pytest.raises(CommandFailedError) as exc:
            await proc.wait()
        assert proc.returncode == 42
        assert str(exc.value) == "Command failed on name with status 42: 'foo'"

    @pytest.mark.asyncio
    async def test_stdin_pipe(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = 0
        proc = await run.run(
            client=self.m_ssh,
            args=['foo'],
            stdin=run.PIPE,
            wait=False
        )
        assert proc.poll() == 0
        code = await proc.wait()
        assert code == 0
        assert proc.exitstatus == 0

    @pytest.mark.asyncio
    async def test_stdout_pipe(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = 0
        lines = [b'one\n', b'two', b'']
        set_buffer_contents(self.m_stdout_buf, lines)
        proc = await run.run(
            client=self.m_ssh,
            args=['foo'],
            stdout=run.PIPE,
            wait=False
        )
        assert proc.poll() == 0
        assert proc.stdout.readline() == lines[0]
        assert proc.stdout.readline() == lines[1]
        assert proc.stdout.readline() == lines[2]
        code = await proc.wait()
        assert code == 0
        assert proc.exitstatus == 0

    @pytest.mark.asyncio
    async def test_stderr_pipe(self):
        self.m_stdout_buf.channel.recv_exit_status.return_value = 0
        lines = [b'one\n', b'two', b'']
        set_buffer_contents(self.m_stderr_buf, lines)
        proc = await run.run(
            client=self.m_ssh,
            args=['foo'],
            stderr=run.PIPE,
            wait=False
        )
        assert proc.poll() == 0
        assert proc.stderr.readline() == lines[0]
        assert proc.stderr.readline() == lines[1]
        assert proc.stderr.readline() == lines[2]
        code = await proc.wait()
        assert code == 0
        assert proc.exitstatus == 0

    @pytest.mark.asyncio
    async def test_copy_and_close(self):
        await run.copy_and_close(None, MagicMock())
        await run.copy_and_close('', MagicMock())
        await run.copy_and_close(b'', MagicMock())


class TestQuote(object):
    def test_quote_simple(self):
        got = run.quote(['a b', ' c', 'd e '])
        assert got == "'a b' ' c' 'd e '"

    def test_quote_and_quote(self):
        got = run.quote(['echo', 'this && is embedded', '&&',
                         'that was standalone'])
        assert got == "echo 'this && is embedded' '&&' 'that was standalone'"

    def test_quote_and_raw(self):
        got = run.quote(['true', run.Raw('&&'), 'echo', 'yay'])
        assert got == "true && echo yay"


class TestRaw(object):
    def test_eq(self):
        str_ = "I am a raw something or other"
        raw = run.Raw(str_)
        assert raw == run.Raw(str_)
