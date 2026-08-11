import os
import yaml

from types import SimpleNamespace
from unittest.mock import patch

from teuthology.config import config
from teuthology.dispatcher import supervisor


MISSING_OSD_DEVICES = r'Wanted \d+ disks? of .+ but only matched \d+'

DISK_FAILURE = {
    'trial007.front.sepia.ceph.com': {
        '_ansible_no_log': False,
        'changed': False,
        'msg': "Wanted 2 disks of ~1700 GB (rotational=False), but only"
               " matched 1: ['nvme1n1']",
    },
}

OTHER_FAILURE = {
    'trial007.front.sepia.ceph.com': {
        'changed': False,
        'msg': 'Failure talking to yum: failure',
    },
}


class TestCheckAnsibleFailureMarkDown(object):
    def setup_method(self):
        # don't depend on whatever lab_domain the site config has
        self.orig_lab_domain = config.lab_domain
        config.lab_domain = 'front.sepia.ceph.com'
        self.the_function = supervisor.check_for_ansible_failures_and_mark_down
        self.patcher = patch.object(
            supervisor,
            'teuth_config',
            SimpleNamespace(disable_targets=dict(
                ansible_failure_patterns=dict(trial=[MISSING_OSD_DEVICES]),
            )),
        )
        self.patcher.start()

    def teardown_method(self, method):
        self.patcher.stop()
        config.lab_domain = self.orig_lab_domain

    def job_config(self, tmp_path, failure_log=None, targets=None):
        if failure_log is not None:
            path = os.path.join(str(tmp_path), supervisor.FAILURE_LOG_NAME)
            with open(path, 'w') as f:
                yaml.safe_dump(failure_log, f)
        if targets is None:
            targets = {
                'ubuntu@trial007.front.sepia.ceph.com': 'ssh-ed25519',
            }
        return dict(
            archive_path=str(tmp_path),
            machine_type='trial',
            targets=targets,
        )

    @patch('teuthology.lock.ops.update_lock')
    def test_disk_failure(self, m_update_lock, tmp_path):
        job_config = self.job_config(tmp_path, DISK_FAILURE)
        assert self.the_function(job_config) == {
            'trial007': DISK_FAILURE['trial007.front.sepia.ceph.com']['msg'],
        }
        m_update_lock.assert_called_once_with('trial007', status='down')

    @patch('teuthology.lock.ops.update_lock')
    def test_other_failure(self, m_update_lock, tmp_path):
        job_config = self.job_config(tmp_path, OTHER_FAILURE)
        self.the_function(job_config)
        assert m_update_lock.called is False

    @patch('teuthology.lock.ops.update_lock')
    def test_no_failure_log(self, m_update_lock, tmp_path):
        job_config = self.job_config(tmp_path)
        self.the_function(job_config)
        assert m_update_lock.called is False

    @patch('teuthology.lock.ops.update_lock')
    def test_host_is_not_a_target(self, m_update_lock, tmp_path):
        job_config = self.job_config(
            tmp_path,
            DISK_FAILURE,
            targets={'ubuntu@trial008.front.sepia.ceph.com': 'ssh-ed25519'},
        )
        self.the_function(job_config)
        assert m_update_lock.called is False

    @patch('teuthology.lock.ops.update_lock')
    def test_no_patterns_for_machine_type(self, m_update_lock, tmp_path):
        job_config = self.job_config(tmp_path, DISK_FAILURE)
        job_config['machine_type'] = 'smithi'
        self.the_function(job_config)
        assert m_update_lock.called is False

    @patch('teuthology.lock.ops.update_lock')
    def test_not_configured(self, m_update_lock, tmp_path):
        job_config = self.job_config(tmp_path, DISK_FAILURE)
        with patch.object(
            supervisor, 'teuth_config', SimpleNamespace(disable_targets=dict())
        ):
            self.the_function(job_config)
        assert m_update_lock.called is False

    @patch('teuthology.lock.ops.update_lock')
    def test_unparseable_failure_log(self, m_update_lock, tmp_path):
        job_config = self.job_config(tmp_path)
        path = os.path.join(str(tmp_path), supervisor.FAILURE_LOG_NAME)
        with open(path, 'w') as f:
            f.write('{not: valid: yaml')
        self.the_function(job_config)
        assert m_update_lock.called is False


class TestDescribeDisabledTargets(object):
    def setup_method(self):
        self.orig_lab_domain = config.lab_domain
        config.lab_domain = 'front.sepia.ceph.com'
        self.the_function = supervisor.describe_disabled_targets
        self.failures = {'trial007': 'Wanted 2 disks, but only matched 1'}

    def teardown_method(self, method):
        config.lab_domain = self.orig_lab_domain

    @patch('teuthology.lock.ops.update_lock')
    @patch('teuthology.lock.query.get_statuses')
    def test_unlocked(self, m_get_statuses, m_update_lock):
        m_get_statuses.return_value = [
            dict(name='trial007.front.sepia.ceph.com', locked=False),
        ]
        self.the_function(self.failures)
        m_update_lock.assert_called_once_with(
            'trial007',
            description='ansible failure: Wanted 2 disks, but only matched 1',
        )

    @patch('teuthology.lock.ops.update_lock')
    @patch('teuthology.lock.query.get_statuses')
    def test_still_locked(self, m_get_statuses, m_update_lock):
        m_get_statuses.return_value = [
            dict(name='trial007.front.sepia.ceph.com', locked=True),
        ]
        self.the_function(self.failures)
        assert m_update_lock.called is False

    @patch('teuthology.lock.ops.update_lock')
    @patch('teuthology.lock.query.get_statuses')
    def test_no_failures(self, m_get_statuses, m_update_lock):
        self.the_function(dict())
        assert m_get_statuses.called is False
        assert m_update_lock.called is False
