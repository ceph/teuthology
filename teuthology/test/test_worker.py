from unittest.mock import patch, Mock, MagicMock
from datetime import datetime, timedelta

from teuthology import worker

from teuthology.contextutil import MaxWhileTries


class TestWorker(object):
    def setup_method(self):
        self.ctx = Mock()
        self.ctx.verbose = True
        self.ctx.archive_dir = '/archive/dir'
        self.ctx.log_dir = '/log/dir'
        self.ctx.tube = 'tube'

    @patch("os.path.exists")
    def test_restart_file_path_doesnt_exist(self, m_exists):
        m_exists.return_value = False
        result = worker.sentinel(worker.restart_file_path)
        assert not result

    @patch("os.path.getmtime")
    @patch("os.path.exists")
    @patch("teuthology.dispatcher.datetime")
    def test_needs_restart(self, m_datetime, m_exists, m_getmtime):
        m_exists.return_value = True
        m_datetime.utcfromtimestamp.return_value = datetime.utcnow() + timedelta(days=1)
        result = worker.sentinel(worker.restart_file_path)
        assert result

    @patch("os.path.getmtime")
    @patch("os.path.exists")
    @patch("teuthology.worker.datetime")
    def test_does_not_need_restart(self, m_datetime, m_exists, getmtime):
        m_exists.return_value = True
        m_datetime.utcfromtimestamp.return_value = datetime.utcnow() - timedelta(days=1)
        result = worker.sentinel(worker.restart_file_path)
        assert not result

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

    @patch("teuthology.worker.run_job")
    @patch("teuthology.worker.prep_job")
    @patch("beanstalkc.Job", autospec=True)
    @patch("teuthology.repo_utils.fetch_qa_suite")
    @patch("teuthology.repo_utils.fetch_teuthology")
    @patch("teuthology.worker.beanstalk.watch_tube")
    @patch("teuthology.worker.beanstalk.connect")
    @patch("os.path.isdir", return_value=True)
    @patch("teuthology.worker.setup_log_file")
    def test_main_loop(
        self, m_setup_log_file, m_isdir, m_connect, m_watch_tube,
        m_fetch_teuthology, m_fetch_qa_suite, m_job, m_prep_job, m_run_job,
                       ):
        m_connection = Mock()
        jobs = self.build_fake_jobs(
            m_connection,
            m_job,
            [
                'foo: bar',
                'stop_worker: true',
            ],
        )
        m_connection.reserve.side_effect = jobs
        m_connect.return_value = m_connection
        m_prep_job.return_value = (dict(), '/bin/path')
        worker.main(self.ctx)
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

    @patch("teuthology.repo_utils.ls_remote")
    @patch("teuthology.dispatcher.supervisor.report.try_push_job_info")
    @patch("teuthology.worker.run_job")
    @patch("beanstalkc.Job", autospec=True)
    @patch("teuthology.repo_utils.fetch_qa_suite")
    @patch("teuthology.repo_utils.fetch_teuthology")
    @patch("teuthology.worker.beanstalk.watch_tube")
    @patch("teuthology.worker.beanstalk.connect")
    @patch("os.path.isdir", return_value=True)
    @patch("teuthology.worker.setup_log_file")
    def test_main_loop_13925(
        self, m_setup_log_file, m_isdir, m_connect, m_watch_tube,
        m_fetch_teuthology, m_fetch_qa_suite, m_job, m_run_job,
        m_try_push_job_info, m_ls_remote,
                       ):
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
        worker.main(self.ctx)
        assert len(m_run_job.call_args_list) == 0
        assert len(m_try_push_job_info.call_args_list) == len(jobs)
        for i in range(len(jobs)):
            push_call = m_try_push_job_info.call_args_list[i]
            assert push_call[0][1]['status'] == 'dead'
