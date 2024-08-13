import os
import pytest
import requests
import contextlib
import yaml

from datetime import datetime, timedelta, timezone
from mock import patch, call, ANY
from io import StringIO
from io import BytesIO

from teuthology.config import config, YamlConfig
from teuthology.exceptions import ScheduleFailError
from teuthology.suite import run
from teuthology.util.time import TIMESTAMP_FMT


class TestRun(object):
    klass = run.Run

    def setup_method(self):
        self.args_dict = dict(
            suite='suite',
            suite_branch='suite_branch',
            suite_relpath='',
            ceph_branch='ceph_branch',
            ceph_sha1='ceph_sha1',
            email='address@example.com',
            teuthology_branch='teuthology_branch',
            kernel_branch=None,
            flavor='flavor',
            distro='ubuntu',
            machine_type='machine_type',
            base_yaml_paths=list(),
        )
        self.args = YamlConfig.from_dict(self.args_dict)

    @patch('teuthology.suite.run.util.fetch_repos')
    @patch('teuthology.suite.run.util.git_ls_remote')
    @patch('teuthology.suite.run.Run.choose_ceph_version')
    @patch('teuthology.suite.run.util.git_validate_sha1')
    def test_email_addr(self, m_git_validate_sha1, m_choose_ceph_version,
                        m_git_ls_remote, m_fetch_repos):
        # neuter choose_X_branch
        m_git_validate_sha1.return_value = self.args_dict['ceph_sha1']
        m_choose_ceph_version.return_value = self.args_dict['ceph_sha1']
        self.args_dict['teuthology_branch'] = 'main'
        self.args_dict['suite_branch'] = 'main'
        m_git_ls_remote.return_value = 'suite_sha1'

        runobj = self.klass(self.args)
        assert runobj.base_config.email == self.args_dict['email']

    @patch('teuthology.suite.run.util.fetch_repos')
    def test_name(self, m_fetch_repos):
        stamp = datetime.now().strftime(TIMESTAMP_FMT)
        with patch.object(run.Run, 'create_initial_config',
                          return_value=run.JobConfig()):
            name = run.Run(self.args).name
        assert str(stamp) in name

    @patch('teuthology.suite.run.util.fetch_repos')
    def test_name_owner(self, m_fetch_repos):
        self.args.owner = 'USER'
        with patch.object(run.Run, 'create_initial_config',
                          return_value=run.JobConfig()):
            name = run.Run(self.args).name
        assert name.startswith('USER-')

    @patch('teuthology.suite.run.util.git_branch_exists')
    @patch('teuthology.suite.run.util.package_version_for_hash')
    @patch('teuthology.suite.run.util.git_ls_remote')
    def test_branch_nonexistent(
        self,
        m_git_ls_remote,
        m_package_version_for_hash,
        m_git_branch_exists,
    ):
        config.gitbuilder_host = 'example.com'
        m_git_ls_remote.side_effect = [
            # First call will be for the ceph hash
            None,
            # Second call will be for the suite hash
            'suite_hash',
        ]
        m_package_version_for_hash.return_value = 'a_version'
        m_git_branch_exists.return_value = True
        self.args.ceph_branch = 'ceph_sha1'
        self.args.ceph_sha1 = None
        with pytest.raises(ScheduleFailError):
            self.klass(self.args)

    @pytest.mark.parametrize(
        ["expire", "delta", "result"],
        [
            [None, timedelta(), False],
            ["1m", timedelta(), True],
            ["1m", timedelta(minutes=-2), False],
            ["1m", timedelta(minutes=2), True],
            ["7d", timedelta(days=-14), False],
        ]
    )
    @patch('teuthology.repo_utils.fetch_repo')
    @patch('teuthology.suite.run.util.git_branch_exists')
    @patch('teuthology.suite.run.util.package_version_for_hash')
    @patch('teuthology.suite.run.util.git_ls_remote')
    def test_get_expiration(
        self,
        m_git_ls_remote,
        m_package_version_for_hash,
        m_git_branch_exists,
        m_fetch_repo,
        expire,
        delta,
        result,
    ):
        m_git_ls_remote.side_effect = 'hash'
        m_package_version_for_hash.return_value = 'a_version'
        m_git_branch_exists.return_value = True
        self.args.expire = expire
        obj = self.klass(self.args)
        now = datetime.now(timezone.utc)
        expires_result = obj.get_expiration(_base_time=now + delta)
        if expire is None:
            assert expires_result is None
            assert obj.base_config['expire'] is None
        else:
            assert expires_result is not None
            assert (now < expires_result) is result
            assert obj.base_config['expire']

    @patch('teuthology.suite.run.util.fetch_repos')
    @patch('requests.head')
    @patch('teuthology.suite.run.util.git_branch_exists')
    @patch('teuthology.suite.run.util.package_version_for_hash')
    @patch('teuthology.suite.run.util.git_ls_remote')
    def test_sha1_exists(
        self,
        m_git_ls_remote,
        m_package_version_for_hash,
        m_git_branch_exists,
        m_requests_head,
        m_fetch_repos,
    ):
        config.gitbuilder_host = 'example.com'
        m_package_version_for_hash.return_value = 'ceph_hash'
        m_git_branch_exists.return_value = True
        resp = requests.Response()
        resp.reason = 'OK'
        resp.status_code = 200
        m_requests_head.return_value = resp
        # only one call to git_ls_remote in this case
        m_git_ls_remote.return_value = "suite_branch"
        run = self.klass(self.args)
        assert run.base_config.sha1 == 'ceph_sha1'
        assert run.base_config.branch == 'ceph_branch'

    @patch('teuthology.suite.run.util.git_ls_remote')
    @patch('requests.head')
    @patch('teuthology.suite.util.git_branch_exists')
    @patch('teuthology.suite.util.package_version_for_hash')
    def test_sha1_nonexistent(
        self,
        m_git_ls_remote,
        m_package_version_for_hash,
        m_git_branch_exists,
        m_requests_head,
    ):
        config.gitbuilder_host = 'example.com'
        m_package_version_for_hash.return_value = 'ceph_hash'
        m_git_branch_exists.return_value = True
        resp = requests.Response()
        resp.reason = 'Not Found'
        resp.status_code = 404
        m_requests_head.return_value = resp
        self.args.ceph_sha1 = 'ceph_hash_dne'
        with pytest.raises(ScheduleFailError):
            self.klass(self.args)

    @patch('teuthology.suite.util.smtplib.SMTP')
    @patch('teuthology.suite.util.git_ls_remote')
    @patch('teuthology.suite.util.package_version_for_hash')
    def test_teuthology_branch_nonexistent(
        self,
        m_pvfh,
        m_git_ls_remote,
        m_smtp,
    ):
        m_git_ls_remote.return_value = None
        config.teuthology_path = None
        config.results_email = "example@example.com"
        self.args.dry_run = True
        self.args.teuthology_branch = 'no_branch'
        with pytest.raises(ScheduleFailError):
            self.klass(self.args)
        m_smtp.assert_not_called()


class TestScheduleSuite(object):
    klass = run.Run

    def setup_method(self):
        self.args_dict = dict(
            suite='suite',
            suite_relpath='',
            suite_dir='suite_dir',
            suite_branch='main',
            ceph_branch='ceph_branch',
            ceph_sha1='ceph_sha1',
            teuthology_branch='main',
            kernel_branch=None,
            flavor='flavor',
            distro='ubuntu',
            distro_version='14.04',
            machine_type='machine_type',
            base_yaml_paths=list(),
        )
        self.args = YamlConfig.from_dict(self.args_dict)

    @patch('teuthology.suite.run.Run.schedule_jobs')
    @patch('teuthology.suite.run.Run.write_rerun_memo')
    @patch('teuthology.suite.util.get_install_task_flavor')
    @patch('teuthology.suite.merge.open')
    @patch('teuthology.suite.run.build_matrix')
    @patch('teuthology.suite.util.git_ls_remote')
    @patch('teuthology.suite.util.package_version_for_hash')
    @patch('teuthology.suite.util.git_validate_sha1')
    @patch('teuthology.suite.util.get_arch')
    def test_successful_schedule(
        self,
        m_get_arch,
        m_git_validate_sha1,
        m_package_version_for_hash,
        m_git_ls_remote,
        m_build_matrix,
        m_open,
        m_get_install_task_flavor,
        m_write_rerun_memo,
        m_schedule_jobs,
    ):
        m_get_arch.return_value = 'x86_64'
        m_git_validate_sha1.return_value = self.args.ceph_sha1
        m_package_version_for_hash.return_value = 'ceph_version'
        m_git_ls_remote.return_value = 'suite_hash'
        build_matrix_desc = 'desc'
        build_matrix_frags = ['frag1.yml', 'frag2.yml']
        build_matrix_output = [
            (build_matrix_desc, build_matrix_frags),
        ]
        m_build_matrix.return_value = build_matrix_output
        frag1_read_output = 'field1: val1'
        frag2_read_output = 'field2: val2'
        m_open.side_effect = [
            StringIO(frag1_read_output),
            StringIO(frag2_read_output),
            contextlib.closing(BytesIO())
        ]
        m_get_install_task_flavor.return_value = 'default'
        m_package_version_for_hash.return_value = "v1"
        # schedule_jobs() is just neutered; check calls below

        self.args.newest = 0
        self.args.num = 42
        runobj = self.klass(self.args)
        runobj.base_args = list()
        count = runobj.schedule_suite()
        assert(count == 1)
        assert runobj.base_config['suite_sha1'] == 'suite_hash'
        m_package_version_for_hash.assert_has_calls(
            [call('ceph_sha1', 'default', 'ubuntu', '14.04', 'machine_type')],
        )
        y = {
          'teuthology': {
            'fragments_dropped': [],
            'meta': {},
            'postmerge': []
          },
          'field1': 'val1',
          'field2': 'val2'
        }
        expected_job = dict(
            yaml=y,
            sha1='ceph_sha1',
            args=[
                '--num',
                '42',
                '--description',
                os.path.join(self.args.suite, build_matrix_desc),
                '--',
                ANY, # base config
                '-'
            ],
            stdin=yaml.dump(y),
            desc=os.path.join(self.args.suite, build_matrix_desc),
        )

        m_schedule_jobs.assert_has_calls(
            [call([], [expected_job], runobj.name)],
        )
        m_write_rerun_memo.assert_called_once_with()

    @patch('teuthology.suite.util.find_git_parents')
    @patch('teuthology.suite.run.Run.schedule_jobs')
    @patch('teuthology.suite.util.get_install_task_flavor')
    @patch('teuthology.suite.run.config_merge')
    @patch('teuthology.suite.run.build_matrix')
    @patch('teuthology.suite.util.git_ls_remote')
    @patch('teuthology.suite.util.package_version_for_hash')
    @patch('teuthology.suite.util.git_validate_sha1')
    @patch('teuthology.suite.util.get_arch')
    def test_newest_failure(
        self,
        m_get_arch,
        m_git_validate_sha1,
        m_package_version_for_hash,
        m_git_ls_remote,
        m_build_matrix,
        m_config_merge,
        m_get_install_task_flavor,
        m_schedule_jobs,
        m_find_git_parents,
    ):
        m_get_arch.return_value = 'x86_64'
        m_git_validate_sha1.return_value = self.args.ceph_sha1
        m_package_version_for_hash.return_value = None
        m_git_ls_remote.return_value = 'suite_hash'
        build_matrix_desc = 'desc'
        build_matrix_frags = ['frag.yml']
        build_matrix_output = [
            (build_matrix_desc, build_matrix_frags),
        ]
        m_build_matrix.return_value = build_matrix_output
        m_config_merge.return_value = [(a, b, {}) for a, b in build_matrix_output]
        m_get_install_task_flavor.return_value = 'default'

        m_find_git_parents.side_effect = lambda proj, sha1, count: [f"{sha1}_{i}" for i in range(11)]

        self.args.newest = 10
        runobj = self.klass(self.args)
        runobj.base_args = list()
        with pytest.raises(ScheduleFailError) as exc:
            runobj.schedule_suite()
        assert 'Exceeded 10 backtracks' in str(exc.value)
        m_find_git_parents.assert_has_calls(
            [call('ceph', 'ceph_sha1', 10)]
        )

    @patch('teuthology.suite.util.find_git_parents')
    @patch('teuthology.suite.run.Run.schedule_jobs')
    @patch('teuthology.suite.run.Run.write_rerun_memo')
    @patch('teuthology.suite.util.get_install_task_flavor')
    @patch('teuthology.suite.run.config_merge')
    @patch('teuthology.suite.run.build_matrix')
    @patch('teuthology.suite.util.git_ls_remote')
    @patch('teuthology.suite.util.package_version_for_hash')
    @patch('teuthology.suite.util.git_validate_sha1')
    @patch('teuthology.suite.util.get_arch')
    def test_newest_success(
        self,
        m_get_arch,
        m_git_validate_sha1,
        m_package_version_for_hash,
        m_git_ls_remote,
        m_build_matrix,
        m_config_merge,
        m_get_install_task_flavor,
        m_write_rerun_memo,
        m_schedule_jobs,
        m_find_git_parents,
    ):
        m_get_arch.return_value = 'x86_64'
        # rig has_packages_for_distro to fail this many times, so
        # everything will run NUM_FAILS+1 times
        NUM_FAILS = 5
        m_git_validate_sha1.return_value = self.args.ceph_sha1
        m_git_ls_remote.return_value = 'suite_hash'
        build_matrix_desc = 'desc'
        build_matrix_frags = ['frag.yml']
        build_matrix_output = [
            (build_matrix_desc, build_matrix_frags),
        ]
        m_build_matrix.return_value = build_matrix_output
        m_config_merge.return_value = [(a, b, {}) for a, b in build_matrix_output]
        m_get_install_task_flavor.return_value = 'default'
        # NUM_FAILS, then success
        m_package_version_for_hash.side_effect = \
            [None for i in range(NUM_FAILS)] + ["ceph_version"]

        m_find_git_parents.side_effect = lambda proj, sha1, count: [f"{sha1}_{i}" for i in range(NUM_FAILS)]

        self.args.newest = 10
        runobj = self.klass(self.args)
        runobj.base_args = list()
        count = runobj.schedule_suite()
        assert count == 1
        m_package_version_for_hash.assert_has_calls(
            [call(f"ceph_sha1_{i}", 'default', 'ubuntu', '14.04', 'machine_type')
             for i in range(NUM_FAILS)]
        )
        m_find_git_parents.assert_has_calls(
            [call('ceph', 'ceph_sha1', 10)]
        )
