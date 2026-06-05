from mock import Mock, MagicMock, patch

from teuthology import provision


class TestDownburst(object):
    def setup_method(self):
        self.ctx = Mock()
        self.ctx.os_type = 'rhel'
        self.ctx.os_version = '7.0'
        self.ctx.config = dict()
        self.name = 'vpm999'
        self.status = dict(
            vm_host=dict(name='host999'),
            is_vm=True,
            machine_type='mtype',
            locked_by='user@a',
            description="desc",
        )

    @patch('teuthology.lock.query.get_status')
    @patch('teuthology.provision.downburst.Downburst')
    def test_create_if_vm_success(self, m_downburst, m_get_status):
        name = self.name
        ctx = self.ctx
        status = self.status
        m_get_status.return_value = status

        dbrst = MagicMock()
        dbrst.executable = '/fake/path'
        dbrst.build_config = MagicMock(name='build_config')
        dbrst._run_create = MagicMock(name='_run_create')
        dbrst._run_create.return_value = (0, '', '')
        dbrst.create.return_value = True
        remove_config = MagicMock(name='remove_config')
        dbrst.remove_config = remove_config
        m_downburst.return_value = dbrst

        result = provision.create_if_vm(ctx, name)
        assert result is True

        dbrst.create.assert_called_with()

    @patch('teuthology.lock.query.get_status')
    @patch('teuthology.provision.downburst.Downburst')
    def test_destroy_if_vm_success(self, m_downburst, m_get_status):
        name = self.name
        status = self.status
        m_get_status.return_value = status

        dbrst = MagicMock()
        dbrst.destroy = MagicMock(name='destroy')
        dbrst.destroy.return_value = True
        m_downburst.return_value = dbrst

        result = provision.destroy_if_vm(name, user="user@a")
        assert result is True

        dbrst.destroy.assert_called_with()

    @patch('teuthology.lock.query.get_status')
    def test_destroy_if_vm_wrong_owner(self, m_get_status):
        name = self.name
        status = self.status
        m_get_status.return_value = status

        result = provision.destroy_if_vm(name, user='user@b')
        assert result is False

    @patch('teuthology.lock.query.get_status')
    def test_destroy_if_vm_wrong_description(self, m_get_status):
        name = self.name
        status = self.status
        m_get_status.return_value = status

        result = provision.destroy_if_vm(name, description='desc_b')
        assert result is False

    @patch('teuthology.provision.downburst.downburst_executable')
    def test_create_fails_without_executable(self, m_exec):
        name = self.name
        ctx = self.ctx
        status = self.status
        m_exec.return_value = ''
        dbrst = provision.downburst.Downburst(
            name, ctx.os_type, ctx.os_version, status)
        result = dbrst.create()
        assert result is False

    @patch('teuthology.provision.downburst.downburst_executable')
    def test_destroy_fails_without_executable(self, m_exec):
        name = self.name
        ctx = self.ctx
        status = self.status
        m_exec.return_value = ''
        dbrst = provision.downburst.Downburst(
            name, ctx.os_type, ctx.os_version, status)
        result = dbrst.destroy()
        assert result is False
