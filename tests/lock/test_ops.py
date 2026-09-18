import json

from unittest.mock import Mock, patch

from teuthology.lock import ops


class TestLockManyOsFilter(object):
    """
    lock_many() should only ask the lock server for a specific
    os_type/os_version when nothing is going to install that OS.
    """

    def setup_method(self):
        self.ctx = Mock()
        self.ctx.machine_type = 'trial'
        response = Mock(ok=True)
        response.json.return_value = []
        self.patchers = [
            patch('teuthology.lock.ops.requests.post',
                  return_value=response),
            patch('teuthology.lock.ops.teuthology.provision.get_reimage_types',
                  return_value=['trial']),
            patch('teuthology.lock.ops.teuthology.provision.cloud.get_types',
                  return_value=[]),
            patch('teuthology.lock.ops.reimage_machines',
                  side_effect=lambda ctx, machines, machine_type: machines),
        ]
        self.m_post = self.patchers[0].start()
        for patcher in self.patchers[1:]:
            patcher.start()
        self.m_reimage = ops.reimage_machines

    def teardown_method(self):
        for patcher in self.patchers:
            patcher.stop()

    def lock_many(self, machine_type, **kwargs):
        self.m_post.reset_mock()
        ops.lock_many(self.ctx, 2, machine_type, 'user@host', 'desc',
                      'rocky', '10', **kwargs)
        assert self.m_post.call_count == 1
        return json.loads(self.m_post.call_args[1]['data'])

    def test_reimage_type(self):
        data = self.lock_many('trial')
        assert 'os_type' not in data
        assert 'os_version' not in data
        assert self.m_reimage.called

    def test_reimage_type_reimaged_later(self):
        # The dispatcher locks with reimage=False; its supervisor reimages
        data = self.lock_many('trial', reimage=False)
        assert 'os_type' not in data
        assert 'os_version' not in data
        assert not self.m_reimage.called

    def test_reimage_type_as_is(self):
        # teuthology-lock --lock-many --no-reimage
        data = self.lock_many('trial', as_is=True)
        assert data['os_type'] == 'rocky'
        assert data['os_version'] == '10'
        assert not self.m_reimage.called

    def test_non_reimage_type(self):
        data = self.lock_many('smithi', reimage=False)
        assert data['os_type'] == 'rocky'
        assert data['os_version'] == '10'
        data = self.lock_many('smithi')
        assert data['os_type'] == 'rocky'
        assert data['os_version'] == '10'
        assert not self.m_reimage.called
