from mock import patch

import teuthology.lock.util
import teuthology.lock.query

class TestLock(object):

    def test_locked_since_seconds(self):
        node = { "locked_since": "2013-02-07 19:33:55.000000" }
        assert teuthology.lock.util.locked_since_seconds(node) > 3600

    @patch('teuthology.lock.query.list_locks')
    def test_get_arch_fail(self, m_query_list_locks):
        m_query_list_locks.return_value = False
        teuthology.lock.query.get_arch('magna')
        m_query_list_locks.assert_called_with(machine_type="magna", count=1, tries=1)

    @patch('teuthology.lock.query.list_locks')
    def test_get_arch_success(self, m_query_list_locks):
        m_query_list_locks.return_value = [{"arch": "arch"}]
        result = teuthology.lock.query.get_arch('magna')
        m_query_list_locks.assert_called_with(
            machine_type="magna",
            count=1, tries=1
        )
        assert result == "arch"
