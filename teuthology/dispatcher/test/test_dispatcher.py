import datetime
import os
import pytest

from unittest.mock import patch, Mock, MagicMock

from teuthology import dispatcher
from teuthology.config import FakeNamespace
from teuthology.contextutil import MaxWhileTries
from teuthology.util.time import TIMESTAMP_FMT


class TestDispatcher(object):
    @pytest.fixture(autouse=True)
    def setup_method(self, tmp_path):
        self.ctx = FakeNamespace()
        self.ctx.verbose = True
        self.ctx.archive_dir = str(tmp_path / "archive/dir")
        self.ctx.log_dir = str(tmp_path / "log/dir")
        self.ctx.tube = 'tube'

    @patch("os.path.exists")
    def test_restart_file_path_doesnt_exist(self, m_exists):
        m_exists.return_value = False
        result = dispatcher.sentinel(dispatcher.restart_file_path)
        assert not result

    @patch("os.path.getmtime")
    @patch("os.path.exists")
    def test_needs_restart(self, m_exists, m_getmtime):
        m_exists.return_value = True
        now = datetime.datetime.now(datetime.timezone.utc)
        m_getmtime.return_value = (now + datetime.timedelta(days=1)).timestamp()
        assert dispatcher.sentinel(dispatcher.restart_file_path)

    @patch("os.path.getmtime")
    @patch("os.path.exists")
    def test_does_not_need_restart(self, m_exists, m_getmtime):
        m_exists.return_value = True
        now = datetime.datetime.now(datetime.timezone.utc)
        m_getmtime.return_value = (now - datetime.timedelta(days=1)).timestamp()
        assert not dispatcher.sentinel(dispatcher.restart_file_path)

    @patch("teuthology.repo_utils.ls_remote")
    @patch("os.path.isdir")
    @patch("teuthology.repo_utils.fetch_teuthology")
    @patch("teuthology.dispatcher.teuth_config")
    @patch("teuthology.repo_utils.fetch_qa_suite")
    def test_prep_job(self, m_fetch_qa_suite, m_teuth_config,
            m_fetch_teuthology, m_isdir, m_ls_remote):
        config = dict(
            name="the_name",
            job_id="1",
            suite_sha1="suite_hash",
        )
        m_fetch_teuthology.return_value = '/teuth/path'
        m_fetch_qa_suite.return_value = '/suite/path'
        m_ls_remote.return_value = 'teuth_hash'
        m_isdir.return_value = True
        m_teuth_config.teuthology_path = None
        got_config, teuth_bin_path = dispatcher.prep_job(
            config,
            self.ctx.log_dir,
            self.ctx.archive_dir,
        )
        assert got_config['worker_log'] == self.ctx.log_dir
        assert got_config['archive_path'] == os.path.join(
            self.ctx.archive_dir,
            config['name'],
            config['job_id'],
        )
        assert got_config['teuthology_branch'] == 'main'
        m_fetch_teuthology.assert_called_once_with(branch='main', commit='teuth_hash')
        assert teuth_bin_path == '/teuth/path/virtualenv/bin'
        m_fetch_qa_suite.assert_called_once_with('main', 'suite_hash')
        assert got_config['suite_path'] == '/suite/path'

    def build_fake_jobs(self, m_connection, m_job, job_bodies):
        """
        Given patched copies of:
            beanstalkc.Connection
            beanstalkc.Job
        And a list of basic job bodies, return a list of mocked Job objects
        """
        # Make sure instantiating m_job returns a new object each time
        jobs = []
        job_id = 0
        for job_body in job_bodies:
            job_id += 1
            job = MagicMock(conn=m_connection, jid=job_id, body=job_body)
            job.jid = job_id
            job.body = job_body
            jobs.append(job)
        return jobs

    @patch("teuthology.dispatcher.find_dispatcher_processes")
    @patch("teuthology.repo_utils.ls_remote")
    @patch("teuthology.dispatcher.report.try_push_job_info")
    @patch("teuthology.dispatcher.supervisor.run_job")
    @patch("beanstalkc.Job", autospec=True)
    @patch("teuthology.repo_utils.fetch_qa_suite")
    @patch("teuthology.repo_utils.fetch_teuthology")
    @patch("teuthology.dispatcher.beanstalk.watch_tube")
    @patch("teuthology.dispatcher.beanstalk.connect")
    @patch("os.path.isdir", return_value=True)
    @patch("teuthology.dispatcher.setup_log_file")
    def test_main_loop(
        self, m_setup_log_file, m_isdir, m_connect, m_watch_tube,
        m_fetch_teuthology, m_fetch_qa_suite, m_job, m_run_job,
        m_try_push_job_info, m_ls_remote, m_find_dispatcher_processes,
                       ):
        m_find_dispatcher_processes.return_value = {}
        m_connection = Mock()
        jobs = self.build_fake_jobs(
            m_connection,
            m_job,
            [
                'name: name\nfoo: bar',
                'name: name\nstop_worker: true',
            ],
        )
        m_connection.reserve.side_effect = jobs
        m_connect.return_value = m_connection
        dispatcher.main(self.ctx)
        # There should be one reserve call per item in the jobs list
        expected_reserve_calls = [
            dict(timeout=60) for i in range(len(jobs))
        ]
        got_reserve_calls = [
            call[1] for call in m_connection.reserve.call_args_list
        ]
        assert got_reserve_calls == expected_reserve_calls
        for job in jobs:
            job.bury.assert_called_once_with()
            job.delete.assert_called_once_with()

    @patch("teuthology.dispatcher.find_dispatcher_processes")
    @patch("teuthology.repo_utils.ls_remote")
    @patch("teuthology.dispatcher.report.try_push_job_info")
    @patch("teuthology.dispatcher.supervisor.run_job")
    @patch("beanstalkc.Job", autospec=True)
    @patch("teuthology.repo_utils.fetch_qa_suite")
    @patch("teuthology.repo_utils.fetch_teuthology")
    @patch("teuthology.dispatcher.beanstalk.watch_tube")
    @patch("teuthology.dispatcher.beanstalk.connect")
    @patch("os.path.isdir", return_value=True)
    @patch("teuthology.dispatcher.setup_log_file")
    def test_main_loop_13925(
        self, m_setup_log_file, m_isdir, m_connect, m_watch_tube,
        m_fetch_teuthology, m_fetch_qa_suite, m_job, m_run_job,
        m_try_push_job_info, m_ls_remote, m_find_dispatcher_processes,
                       ):
        m_find_dispatcher_processes.return_value = {}
        m_connection = Mock()
        jobs = self.build_fake_jobs(
            m_connection,
            m_job,
            [
                'name: name',
                'name: name\nstop_worker: true',
            ],
        )
        m_connection.reserve.side_effect = jobs
        m_connect.return_value = m_connection
        m_fetch_qa_suite.side_effect = [
            '/suite/path',
            MaxWhileTries(),
            MaxWhileTries(),
        ]
        dispatcher.main(self.ctx)
        assert len(m_run_job.call_args_list) == 0
        assert len(m_try_push_job_info.call_args_list) == len(jobs)
        for i in range(len(jobs)):
            push_call = m_try_push_job_info.call_args_list[i]
            assert push_call[0][1]['status'] == 'dead'

    @pytest.mark.parametrize(
        ["timestamp", "expire", "skip"],
        [
            [datetime.timedelta(days=-1), None, False],
            [datetime.timedelta(days=-30), None, True],
            [None, datetime.timedelta(days=1), False],
            [None, datetime.timedelta(days=-1), True],
            [datetime.timedelta(days=-1), datetime.timedelta(days=1), False],
            [datetime.timedelta(days=1), datetime.timedelta(days=-1), True],
        ]
    )
    @patch("teuthology.dispatcher.report.try_push_job_info")
    def test_check_job_expiration(self, _, timestamp, expire, skip):
        now = datetime.datetime.now(datetime.timezone.utc)
        job_config = dict(
            job_id="1",
            name="job_name",
        )
        if timestamp:
            job_config["timestamp"] = (now + timestamp).strftime(TIMESTAMP_FMT)
        if expire:
            job_config["expire"] = (now + expire).strftime(TIMESTAMP_FMT)
        if skip:
            with pytest.raises(dispatcher.SkipJob):
                dispatcher.check_job_expiration(job_config)
        else:
            dispatcher.check_job_expiration(job_config)
