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

    def test_create_if_vm_success(self):
        name = self.name
        ctx = self.ctx
        status = self.status

        dbrst = provision.downburst.Downburst(
            name, ctx.os_type, ctx.os_version, status)
        dbrst.executable = '/fake/path'
        dbrst.build_config = MagicMock(name='build_config')
        dbrst._run_create = MagicMock(name='_run_create')
        dbrst._run_create.return_value = (0, '', '')
        remove_config = MagicMock(name='remove_config')
        dbrst.remove_config = remove_config

        result = provision.create_if_vm(ctx, name, dbrst)
        assert result is True

        dbrst._run_create.assert_called_with()
        dbrst.build_config.assert_called_with()
        del dbrst
        remove_config.assert_called_with()

    def test_destroy_if_vm_success(self):
        name = self.name
        ctx = self.ctx
        status = self.status

        dbrst = provision.downburst.Downburst(
            name, ctx.os_type, ctx.os_version, status)
        dbrst.destroy = MagicMock(name='destroy')
        dbrst.destroy.return_value = True

        result = provision.destroy_if_vm(name, user="user@a", _downburst=dbrst)
        assert result is True

        dbrst.destroy.assert_called_with()

    def test_destroy_if_vm_wrong_owner(self):
        name = self.name
        ctx = self.ctx
        status = self.status

        dbrst = provision.downburst.Downburst(
            name, ctx.os_type, ctx.os_version, status)
        dbrst.destroy = MagicMock(name='destroy', side_effect=RuntimeError)

        result = provision.destroy_if_vm(name, user='user@b',
                                         _downburst=dbrst)
        assert result is False

    def test_destroy_if_vm_wrong_description(self):
        name = self.name
        ctx = self.ctx
        status = self.status

        dbrst = provision.downburst.Downburst(
            name, ctx.os_type, ctx.os_version, status)
        dbrst.destroy = MagicMock(name='destroy')
        dbrst.destroy = MagicMock(name='destroy', side_effect=RuntimeError)

        result = provision.destroy_if_vm(name, description='desc_b',
                                         _downburst=dbrst)
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
