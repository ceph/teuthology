from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

from teuthology.lock import ops


@contextmanager
def fake_safe_while(*args, **kwargs):
    called = {'n': 0}

    def proceed():
        called['n'] += 1
        return called['n'] == 1

    yield proceed


def _unlock_context(machine_type, m_update_lock):
    status = {
        'machine_type': machine_type,
        'description': None,
        'is_vm': False,
    }
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    stack = ExitStack()
    stack.enter_context(patch(
        'teuthology.lock.ops.teuthology.provision.destroy_if_vm',
        return_value=True,
    ))
    stack.enter_context(patch(
        'teuthology.lock.ops.query.get_status', return_value=status,
    ))
    stack.enter_context(patch(
        'teuthology.lock.ops.query.is_vm', return_value=False,
    ))
    stack.enter_context(patch('teuthology.lock.ops.stop_node'))
    stack.enter_context(patch(
        'teuthology.lock.ops.requests.put', return_value=resp,
    ))
    stack.enter_context(patch(
        'teuthology.lock.ops.safe_while', fake_safe_while,
    ))
    stack.enter_context(patch(
        'teuthology.lock.ops.update_lock', m_update_lock,
    ))
    stack.enter_context(patch(
        'teuthology.lock.ops.provision.openshift.get_types',
        return_value=['ocpvirt'],
    ))
    stack.enter_context(patch(
        'teuthology.lock.ops.config.lock_server', 'http://paddles',
    ))
    stack.enter_context(patch(
        'teuthology.lock.ops.misc.canonicalize_hostname',
        side_effect=lambda n, user=None: n,
    ))
    return stack


class TestUnlockOps:
    def test_unlock_openshift_marks_down(self):
        m_update_lock = MagicMock()
        with _unlock_context('ocpvirt', m_update_lock):
            assert ops.unlock_one('target-002', 'teuthology') is True
        m_update_lock.assert_called_once_with('target-002', status='down')

    def test_unlock_non_openshift_does_not_mark_down(self):
        m_update_lock = MagicMock()
        with _unlock_context('smithi', m_update_lock):
            assert ops.unlock_one('smithi001', 'teuthology') is True
        m_update_lock.assert_not_called()
