import os

from mock import patch

from teuthology.config import FakeNamespace
from teuthology.config import config as teuth_config
from teuthology.orchestra.cluster import Cluster
from teuthology.orchestra.remote import Remote
from teuthology.task.console_log import ConsoleLog

from teuthology.test.task import TestTask


class TestConsoleLog(TestTask):
    klass = ConsoleLog
    task_name = 'console_log'

    def setup_method(self):
        teuth_config.ipmi_domain = 'ipmi.domain'
        teuth_config.ipmi_user = 'ipmi_user'
        teuth_config.ipmi_password = 'ipmi_pass'
        self.ctx = FakeNamespace()
        self.ctx.cluster = Cluster()
        self.ctx.cluster.add(Remote('user@remote1'), ['role1'])
        self.ctx.cluster.add(Remote('user@remote2'), ['role2'])
        self.ctx.config = dict()
        self.ctx.archive = '/fake/path'
        self.task_config = dict()
        self.start_patchers()

    def start_patchers(self):
        self.patchers = dict()
        self.patchers['makedirs'] = patch(
            'teuthology.task.console_log.os.makedirs',
        )
        self.patchers['is_vm'] = patch(
            'teuthology.lock.query.is_vm',
        )
        self.patchers['is_vm'].return_value = False
        self.patchers['get_status'] = patch(
            'teuthology.lock.query.get_status',
        )
        self.mocks = dict()
        for name, patcher in self.patchers.items():
            self.mocks[name] = patcher.start()
        self.mocks['is_vm'].return_value = False

    def teardown_method(self):
        for patcher in self.patchers.values():
            patcher.stop()

    def test_enabled(self):
        task = self.klass(self.ctx, self.task_config)
        assert task.enabled is True

    def test_disabled_noarchive(self):
        self.ctx.archive = None
        task = self.klass(self.ctx, self.task_config)
        assert task.enabled is False

    def test_has_ipmi_credentials(self):
        for remote in self.ctx.cluster.remotes.keys():
            remote.console.has_ipmi_credentials = False
            remote.console.has_conserver = False
        task = self.klass(self.ctx, self.task_config)
        assert len(task.cluster.remotes.keys()) == 0

    def test_remotes(self):
        with self.klass(self.ctx, self.task_config) as task:
            assert len(task.cluster.remotes) == len(self.ctx.cluster.remotes)

    @patch('teuthology.orchestra.console.PhysicalConsole')
    def test_begin(self, m_pconsole):
        with self.klass(self.ctx, self.task_config) as task:
            assert len(task.processes) == len(self.ctx.cluster.remotes)
            expected_log_paths = []
            for remote in task.cluster.remotes.keys():
                expected_log_paths.append(
                    os.path.join(self.ctx.archive, 'console_logs', '%s.log' % remote.shortname)
                )
            assert len(m_pconsole().spawn_sol_log.call_args_list) == len(task.cluster.remotes)
            got_log_paths = [c[0][0] for c in m_pconsole().spawn_sol_log.call_args_list]
            assert got_log_paths == expected_log_paths

    @patch('teuthology.orchestra.console.PhysicalConsole')
    def test_end(self, m_pconsole):
        m_proc = m_pconsole().spawn_sol_log.return_value
        m_proc.poll.return_value = None
        with self.klass(self.ctx, self.task_config):
            pass
        assert len(m_proc.terminate.call_args_list) == len(self.ctx.cluster.remotes)
        assert len(m_proc.kill.call_args_list) == len(self.ctx.cluster.remotes)
