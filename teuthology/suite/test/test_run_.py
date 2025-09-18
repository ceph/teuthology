import logging
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

log = logging.getLogger(__name__)

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

    @patch('teuthology.suite.run.util.fetch_repos')
    @patch('teuthology.suite.util.git_ls_remote')
    @patch('teuthology.suite.run.util.package_version_for_hash')
    def test_os_type(self, m_pvfh, m_git_ls_remote, m_fetch_repos):
        m_git_ls_remote.return_value = "sha1"
        del self.args['distro']
        run_ = run.Run(self.args)
        run_.base_args = run_.build_base_args()
        run_.base_config = run_.build_base_config()
        configs = [
            ["desc", [], {"os_type": "debian", "os_version": "8.0"}],
            ["desc", [], {"os_type": "ubuntu", "os_version": "24.0"}],
        ]
        missing, to_schedule = run_.collect_jobs('x86_64', configs, False, False)
        assert to_schedule[0]['yaml']['os_type'] == "debian"
        assert to_schedule[0]['yaml']['os_version'] == "8.0"
        assert to_schedule[1]['yaml']['os_type'] == "ubuntu"
        assert to_schedule[1]['yaml']['os_version'] == "24.0"

    @patch('teuthology.suite.run.util.fetch_repos')
    @patch('teuthology.suite.util.git_ls_remote')
    @patch('teuthology.suite.run.util.package_version_for_hash')
    def test_sha1(self, m_pvfh, m_git_ls_remote, m_fetch_repos):
        m_git_ls_remote.return_value = "sha1"
        del self.args['distro']
        run_ = run.Run(self.args)
        run_.base_args = run_.build_base_args()
        for i in range(5): # mock backtracking
            run_.config_input['ceph_hash'] = f"boo{i}"
            run_.config_input['suite_hash'] = f"bar{i}"
            run_.base_config = run_.build_base_config()
        configs = [
            ["desc", [], {"os_type": "debian", "os_version": "8.0", 
                          "sha1": "old_sha", "suite_sha1": "old_sha",
                          "overrides": { "workunit": {"sha1": "old_sha"}, "ceph": {"sha1": "old_sha"} }
                          }],
        ]
        missing, to_schedule = run_.collect_jobs('x86_64', configs, False, False)
        assert to_schedule[0]['yaml']['sha1'] == "boo4"
        assert to_schedule[0]['yaml']['suite_sha1'] == "bar4"
        assert to_schedule[0]['yaml']['overrides']['workunit']["sha1"] == "bar4"
        assert to_schedule[0]['yaml']['overrides']['ceph']["sha1"] == "boo4"

class TestScheduleSuite(object):
    klass = run.Run

    def setup_method(self):
        self.args_dict = dict(
            suite='suite',
            suite_relpath='',
            suite_dir='suite_dir',
            suite_branch='main',
            suite_repo='main',
            ceph_repo='main',
            ceph_branch='main',
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
          'field1': 'val1',
          'field2': 'val2'
        }
        teuthology_keys = [
          'branch',
          'machine_type',
          'name',
          'os_type',
          'os_version',
          'overrides',
          'priority',
          'repo',
          'seed',
          'sha1',
          'sleep_before_teardown',
          'suite',
          'suite_branch',
          'suite_relpath',
          'suite_repo',
          'suite_sha1',
          'tasks',
          'teuthology_branch',
          'teuthology_repo',
          'teuthology_sha1',
          'timestamp',
          'user',
          'teuthology',
          'flavor',
        ]
        for t in teuthology_keys:
            y[t] = ANY
        expected_job = dict(
            yaml=y,
            sha1='ceph_sha1',
            args=[
                '--num',
                '42',
                '--description',
                os.path.join(self.args.suite, build_matrix_desc),
                '--',
                '-'
            ],
            stdin=ANY,
            desc=os.path.join(self.args.suite, build_matrix_desc),
        )

        m_schedule_jobs.assert_has_calls(
            [call([], [expected_job], runobj.name)],
        )
        args = m_schedule_jobs.call_args.args
        log.debug("args =\n%s", args)
        jobargs  = args[1][0]
        stdin_yaml = yaml.safe_load(jobargs['stdin'])
        for k in y:
            assert y[k] == stdin_yaml[k]
        for k in teuthology_keys:
            assert k in stdin_yaml
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
    def test_newest_success_same_branch_same_repo(
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
        """
        Test that we can successfully schedule a job with newest
        backtracking when the ceph and suite branches are the same
        and the ceph_sha1 is not supplied. We should expect that the
        ceph_hash and suite_hash will be updated to the working sha1
        """
        m_get_arch.return_value = 'x86_64'
        # rig has_packages_for_distro to fail this many times, so
        # everything will run NUM_FAILS+1 times
        NUM_FAILS = 5
        # Here we just assume that even fi ceph_sha1 is not supplied,
        # in git_valid_sha1, util.git_ls_remote will give us ceph_sha1
        m_git_validate_sha1.return_value = self.args.ceph_sha1
        # Here we know that in create_initial_config, we call
        # git_ls_remote 3 times, choose_ceph_hash, choose_suite_hash,
        # and choose_teuthology_branch
        sha1_side_effect = [
            self.args.ceph_sha1,  # ceph_sha1
            'suite_sha1',        # suite_sha1
            'teuthology_sha1',   # teuthology_sha1
        ]
        m_git_ls_remote.side_effect = sha1_side_effect
        build_matrix_desc = 'desc'
        build_matrix_frags = ['frag.yml']
        build_matrix_output = [
            (build_matrix_desc, build_matrix_frags),
        ]
        m_build_matrix.return_value = build_matrix_output
        m_config_merge.return_value = [(a, b, {}) for a, b in build_matrix_output]
        m_get_install_task_flavor.return_value = 'default'

        # Generate backtracked parent sha1s
        parent_sha1s = [f"ceph_sha1_{i}" for i in range(NUM_FAILS)]
        assert len(parent_sha1s)
        # Last sha1 will be the one that works!
        working_sha1 = parent_sha1s[-1]

        # NUM_FAILS attempts, then success on the last parent sha1
        m_package_version_for_hash.side_effect = \
            [None for i in range(NUM_FAILS)] + ["ceph_version"]

        m_find_git_parents.return_value = parent_sha1s

        self.args.newest = 10
        runobj = self.klass(self.args)
        runobj.base_args = list()

        # Call schedule_suite()
        count = runobj.schedule_suite()
        # Epect only 1 job to be scheduled
        assert count == 1
        # Expect that we called package_version_for_hash NUM_FAILS times + 1 for the working sha1
        m_package_version_for_hash.assert_has_calls(
            [call(self.args.ceph_sha1, 'default', 'ubuntu', '14.04', 'machine_type')] +
            [call(f"ceph_sha1_{i}", 'default', 'ubuntu', '14.04', 'machine_type')
             for i in range(0, NUM_FAILS)]
        )
        # (ceph, base_config.sha1, newest) called once to get grab the backtrace
        m_find_git_parents.assert_called_once_with('ceph', 'ceph_sha1', 10)

        # Verify that base_config was updated with the working SHA1
        assert runobj.base_config.sha1 == working_sha1

        # Verify that config_input's ceph_hash and suite_hash was updated
        assert runobj.config_input['ceph_hash'] == working_sha1
        assert runobj.config_input['suite_hash'] == working_sha1

        # Verify that config_input's ceph_hash and suite_hash are not the same as the original sha1s
        assert runobj.config_input['ceph_hash'] != sha1_side_effect[0]  # ceph_sha1
        assert runobj.config_input['suite_hash'] != sha1_side_effect[1]  # suite_sha1

        # Verify the sha1 in scheduled jobs
        args = m_schedule_jobs.call_args.args
        scheduled_jobs = args[1]

        # Check each job has the correct SHA1
        for job in scheduled_jobs:
            assert job['sha1'] == working_sha1

            # Parse YAML from stdin to check for sha1 and suite_hash
            if 'stdin' in job:
                job_yaml = yaml.safe_load(job['stdin'])
                assert job_yaml.get('sha1') == working_sha1
                assert job_yaml.get('suite_sha1') == working_sha1

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
    def test_newest_success_diff_branch_diff_repo(
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
        """
        Test that we can successfully schedule a job with newest
        backtracking when the ceph and suite branches are different
        and the ceph_sha1 is not supplied. We should expect that the
        ceph_hash will be updated to the working sha1,
        but the suite_hash will remain the original suite_sha1.
        """
        m_get_arch.return_value = 'x86_64'
        # Set different branches
        self.args.ceph_branch = 'ceph_different_branch'
        self.args.suite_branch = 'suite_different_branch'

        # rig has_packages_for_distro to fail this many times, so
        # everything will run NUM_FAILS+1 times
        NUM_FAILS = 5
        # Here we just assume that even fi ceph_sha1 is not supplied,
        # in git_valid_sha1, util.git_ls_remote will give us ceph_sha1
        m_git_validate_sha1.return_value = self.args.ceph_sha1
        # Here we know that in create_initial_config, we call
        # git_ls_remote 3 times, choose_ceph_hash, choose_suite_hash,
        # and choose_teuthology_branch
        sha1_side_effect = [
            self.args.ceph_sha1,  # ceph_sha1
            'suite_sha1',        # suite_sha1
            'teuthology_sha1',   # teuthology_sha1
        ]
        m_git_ls_remote.side_effect = sha1_side_effect
        build_matrix_desc = 'desc'
        build_matrix_frags = ['frag.yml']
        build_matrix_output = [
            (build_matrix_desc, build_matrix_frags),
        ]
        m_build_matrix.return_value = build_matrix_output
        m_config_merge.return_value = [(a, b, {}) for a, b in build_matrix_output]
        m_get_install_task_flavor.return_value = 'default'

        # Generate backtracked parent sha1s
        parent_sha1s = [f"ceph_sha1_{i}" for i in range(NUM_FAILS)]
        assert len(parent_sha1s)
        # Last sha1 will be the one that works!
        working_sha1 = parent_sha1s[-1]

        # NUM_FAILS attempts, then success on the last parent sha1
        m_package_version_for_hash.side_effect = \
            [None for i in range(NUM_FAILS)] + ["ceph_version"]

        m_find_git_parents.return_value = parent_sha1s

        self.args.newest = 10
        runobj = self.klass(self.args)
        runobj.base_args = list()

        # Call schedule_suite()
        count = runobj.schedule_suite()
        # Epect only 1 job to be scheduled
        assert count == 1
        # Expect that we called package_version_for_hash NUM_FAILS times + 1 for the working sha1
        m_package_version_for_hash.assert_has_calls(
            [call(self.args.ceph_sha1, 'default', 'ubuntu', '14.04', 'machine_type')] +
            [call(f"ceph_sha1_{i}", 'default', 'ubuntu', '14.04', 'machine_type')
             for i in range(0, NUM_FAILS)]
        )
        # (ceph, base_config.sha1, newest) called once to get grab the backtrace
        m_find_git_parents.assert_called_once_with('ceph', 'ceph_sha1', 10)

        # Verify that base_config was updated with the working SHA1
        assert runobj.base_config.sha1 == working_sha1

        # Verify that config_input's ceph_hash was updated,
        # but suite_hash is still the original suite_sha1
        assert runobj.config_input['ceph_hash'] == working_sha1
        assert runobj.config_input['suite_hash'] != working_sha1

        # Verify that config_input's ceph_hash is not the same as the original sha1s
        # but suite_hash is still the original suite_sha1
        assert runobj.config_input['ceph_hash'] != sha1_side_effect[0]  # ceph_sha1
        assert runobj.config_input['suite_hash'] == sha1_side_effect[1]  # suite_sha1

        # Verify the sha1 in scheduled jobs
        args = m_schedule_jobs.call_args.args
        scheduled_jobs = args[1]

        # Check each job has the correct SHA1
        for job in scheduled_jobs:
            assert job['sha1'] == working_sha1

            # Parse YAML from stdin to check for sha1 and suite_hash
            if 'stdin' in job:
                job_yaml = yaml.safe_load(job['stdin'])
                assert job_yaml.get('sha1') == working_sha1
                assert job_yaml.get('suite_sha1') == sha1_side_effect[1]
