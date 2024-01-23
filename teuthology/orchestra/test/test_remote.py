import pytest

from mock import patch, Mock, MagicMock, AsyncMock

from io import BytesIO

from teuthology.orchestra import remote
from teuthology.orchestra import opsys
from teuthology.orchestra.run import RemoteProcess
from teuthology.exceptions import CommandFailedError, UnitTestError


class TestRemote(object):

    def setup_method(self):
        self.start_patchers()

    def teardown_method(self):
        self.stop_patchers()

    def start_patchers(self):
        self.m_ssh = MagicMock()
        self.patcher_ssh = patch(
            'teuthology.orchestra.connection.paramiko.SSHClient',
            self.m_ssh,
        )
        self.patcher_ssh.start()

    def stop_patchers(self):
        self.patcher_ssh.stop()

    def test_shortname(self):
        r = remote.Remote(
            name='jdoe@xyzzy.example.com',
            shortname='xyz',
            ssh=self.m_ssh,
            )
        assert r.shortname == 'xyz'
        assert str(r) == 'jdoe@xyzzy.example.com'

    def test_shortname_default(self):
        r = remote.Remote(
            name='jdoe@xyzzy.example.com',
            ssh=self.m_ssh,
            )
        assert r.shortname == 'xyzzy'
        assert str(r) == 'jdoe@xyzzy.example.com'

    @pytest.mark.asyncio
    async def test_run(self):
        m_transport = MagicMock()
        m_transport.getpeername.return_value = ('name', 22)
        self.m_ssh.get_transport.return_value = m_transport
        m_run = AsyncMock()
        args = [
            'something',
            'more',
            ]
        proc = RemoteProcess(
            client=self.m_ssh,
            args=args,
            )
        m_run.return_value = proc
        rem = remote.Remote(name='jdoe@xyzzy.example.com', ssh=self.m_ssh)
        rem._runner = m_run
        result = await rem.run(args=args)
        m_transport.getpeername.assert_called_once_with()
        m_run_call_kwargs = m_run.call_args_list[0][1]
        assert m_run_call_kwargs['args'] == args
        assert result is proc
        assert result.remote is rem

    @pytest.mark.asyncio
    @patch('teuthology.util.scanner.UnitTestScanner.scan_and_write')
    async def test_run_unit_test(self, m_scan_and_write):
        m_transport = MagicMock()
        m_transport.getpeername.return_value = ('name', 22)
        self.m_ssh.get_transport.return_value = m_transport
        m_run = AsyncMock(name="run", side_effect=CommandFailedError('mocked error', 1, 'smithi'))
        args = [
            'something',
            'more',
        ]
        rem = remote.Remote(name='jdoe@xyzzy.example.com', ssh=self.m_ssh)
        rem._runner = m_run
        m_scan_and_write.return_value = "Error Message"
        with pytest.raises(UnitTestError) as exc:
            await rem.run_unit_test(args=args, xml_path_regex="xml_path", output_yaml="yaml_path")
        assert str(exc.value) == "Unit test failed on smithi with status 1: 'Error Message'"

    @pytest.mark.asyncio
    async def test_hostname(self):
        m_transport = MagicMock()
        m_transport.getpeername.return_value = ('name', 22)
        self.m_ssh.get_transport.return_value = m_transport
        m_run = AsyncMock()
        args = [
            'hostname',
            '--fqdn',
            ]
        stdout = BytesIO(b'test_hostname')
        stdout.seek(0)
        proc = RemoteProcess(
            client=self.m_ssh,
            args=args,
            )
        proc.stdout = stdout
        proc._stdout_buf = Mock()
        proc._stdout_buf.channel.recv_exit_status.return_value = 0
        r = remote.Remote(name='xyzzy.example.com', ssh=self.m_ssh)
        m_run.return_value = proc
        r._runner = m_run
        assert await r.hostname() == 'test_hostname'

    @pytest.mark.asyncio
    async def test_arch(self):
        m_transport = MagicMock()
        m_transport.getpeername.return_value = ('name', 22)
        self.m_ssh.get_transport.return_value = m_transport
        m_run = AsyncMock()
        args = [
            'uname',
            '-m',
            ]
        stdout = BytesIO(b'test_arch')
        stdout.seek(0)
        proc = RemoteProcess(
            client=self.m_ssh,
            args=args,
            )
        proc._stdout_buf = Mock()
        proc._stdout_buf.channel = Mock()
        proc._stdout_buf.channel.recv_exit_status.return_value = 0
        proc._stdout_buf.channel.expects('recv_exit_status').returns(0)
        proc.stdout = stdout
        m_run.return_value = proc
        r = remote.Remote(name='jdoe@xyzzy.example.com', ssh=self.m_ssh)
        r._runner = m_run
        assert await r.arch() == 'test_arch'
        assert len(m_run.call_args_list) == 1
        m_run_call_kwargs = m_run.call_args_list[0][1]
        assert m_run_call_kwargs['client'] == self.m_ssh
        assert m_run_call_kwargs['name'] == r.shortname
        assert m_run_call_kwargs['args'] == ' '.join(args)

    def test_host_key(self):
        m_key = MagicMock()
        m_key.get_name.return_value = 'key_type'
        m_key.get_base64.return_value = 'test ssh key'
        m_transport = MagicMock()
        m_transport.get_remote_server_key.return_value = m_key
        self.m_ssh.get_transport.return_value = m_transport
        r = remote.Remote(name='jdoe@xyzzy.example.com', ssh=self.m_ssh)
        assert r.host_key == 'key_type test ssh key'
        self.m_ssh.get_transport.assert_called_once_with()
        m_transport.get_remote_server_key.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_inventory_info(self):
        r = remote.Remote('user@host', host_key='host_key')
        r._arch = 'arch'
        r._os = opsys.OS(name='os_name', version='1.2.3', codename='code')
        inv_info = await r.inventory_info()
        assert inv_info == dict(
            name='host',
            user='user',
            arch='arch',
            os_type='os_name',
            os_version='1.2',
            ssh_pub_key='host_key',
            up=True,
        )

    def test_sftp_open_file(self):
        m_file_obj = MagicMock()
        m_stat = Mock()
        m_stat.st_size = 42
        m_file_obj.stat.return_value = m_stat
        m_open = MagicMock()
        m_open.return_value = m_file_obj
        m_open.return_value.__enter__.return_value = m_file_obj
        with patch.object(remote.Remote, '_sftp_open_file', new=m_open):
            rem = remote.Remote(name='jdoe@xyzzy.example.com', ssh=self.m_ssh)
            assert rem._sftp_open_file('x') is m_file_obj
            assert rem._sftp_open_file('x').stat() is m_stat
            assert rem._sftp_open_file('x').stat().st_size == 42
            with rem._sftp_open_file('x') as f:
                assert f == m_file_obj

    def test_sftp_get_size(self):
        m_file_obj = MagicMock()
        m_stat = Mock()
        m_stat.st_size = 42
        m_file_obj.stat.return_value = m_stat
        m_open = MagicMock()
        m_open.return_value = m_file_obj
        m_open.return_value.__enter__.return_value = m_file_obj
        with patch.object(remote.Remote, '_sftp_open_file', new=m_open):
            rem = remote.Remote(name='jdoe@xyzzy.example.com', ssh=self.m_ssh)
            assert rem._sftp_get_size('/fake/file') == 42

    def test_format_size(self):
        assert remote.Remote._format_size(1023).strip() == '1023B'
        assert remote.Remote._format_size(1024).strip() == '1KB'
        assert remote.Remote._format_size(1024**2).strip() == '1MB'
        assert remote.Remote._format_size(1024**5).strip() == '1TB'
        assert remote.Remote._format_size(1021112).strip() == '997KB'
        assert remote.Remote._format_size(1021112**2).strip() == '971GB'

    @pytest.mark.asyncio
    async def test_is_container(self):
        m_transport = MagicMock()
        m_transport.getpeername.return_value = ('name', 22)
        self.m_ssh.get_transport.return_value = m_transport
        m_run = AsyncMock()
        args = []
        proc = RemoteProcess(
            client=self.m_ssh,
            args=args,
        )
        proc.returncode = 0
        m_run.return_value = proc
        rem = remote.Remote(name='jdoe@xyzzy.example.com', ssh=self.m_ssh)
        rem._runner = m_run
        assert await rem.is_container() is True
        proc.returncode = 1
        rem2 = remote.Remote(name='jdoe@xyzzy.example.com', ssh=self.m_ssh)
        rem2._runner = m_run
        assert await rem2.is_container() is False
