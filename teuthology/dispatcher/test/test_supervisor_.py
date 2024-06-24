from subprocess import DEVNULL
from unittest.mock import patch, Mock, MagicMock

from teuthology.dispatcher import supervisor


class TestSuperviser(object):
    @patch("teuthology.dispatcher.supervisor.run_with_watchdog")
    @patch("teuthology.dispatcher.supervisor.teuth_config")
    @patch("subprocess.Popen")
    @patch("os.environ")
    @patch("os.mkdir")
    @patch("yaml.safe_dump")
    @patch("tempfile.NamedTemporaryFile")
    def test_run_job_with_watchdog(self, m_tempfile, m_safe_dump, m_mkdir,
                                   m_environ, m_popen, m_t_config,
                                   m_run_watchdog):
        config = {
            "suite_path": "suite/path",
            "config": {"foo": "bar"},
            "verbose": True,
            "owner": "the_owner",
            "archive_path": "archive/path",
            "name": "the_name",
            "description": "the_description",
            "job_id": "1",
        }
        m_tmp = MagicMock()
        temp_file = Mock()
        temp_file.name = "the_name"
        m_tmp.__enter__.return_value = temp_file
        m_tempfile.return_value = m_tmp
        m_p = Mock()
        m_p.returncode = 0
        m_popen.return_value = m_p
        m_t_config.results_server = True
        supervisor.run_job(config, "teuth/bin/path", "archive/dir", verbose=False)
        m_run_watchdog.assert_called_with(m_p, config)
        expected_args = [
            'teuth/bin/path/teuthology',
            '-v',
            '--owner', 'the_owner',
            '--archive', 'archive/path',
            '--name', 'the_name',
            '--description',
            'the_description',
            '--',
            "archive/path/orig.config.yaml",
        ]
        m_popen.assert_called_with(args=expected_args, stderr=DEVNULL, stdout=DEVNULL)

    @patch("time.sleep")
    @patch("teuthology.dispatcher.supervisor.teuth_config")
    @patch("subprocess.Popen")
    @patch("os.environ")
    @patch("os.mkdir")
    @patch("yaml.safe_dump")
    @patch("tempfile.NamedTemporaryFile")
    def test_run_job_no_watchdog(self, m_tempfile, m_safe_dump, m_mkdir,
                                 m_environ, m_popen, m_t_config,
                                 m_sleep):
        config = {
            "suite_path": "suite/path",
            "config": {"foo": "bar"},
            "verbose": True,
            "owner": "the_owner",
            "archive_path": "archive/path",
            "name": "the_name",
            "description": "the_description",
            "job_id": "1",
        }
        m_tmp = MagicMock()
        temp_file = Mock()
        temp_file.name = "the_name"
        m_tmp.__enter__.return_value = temp_file
        m_tempfile.return_value = m_tmp
        env = dict(PYTHONPATH="python/path")
        m_environ.copy.return_value = env
        m_p = Mock()
        m_p.returncode = 1
        m_popen.return_value = m_p
        m_t_config.results_server = False
        supervisor.run_job(config, "teuth/bin/path", "archive/dir", verbose=False)

    @patch("teuthology.dispatcher.supervisor.report.try_push_job_info")
    @patch("time.sleep")
    def test_run_with_watchdog_no_reporting(self, m_sleep, m_try_push):
        config = {
            "name": "the_name",
            "job_id": "1",
            "archive_path": "archive/path",
            "teuthology_branch": "main"
        }
        process = Mock()
        process.poll.return_value = "not None"
        supervisor.run_with_watchdog(process, config)
        m_try_push.assert_called_with(
            dict(name=config["name"], job_id=config["job_id"]),
            dict(status='dead')
        )

    @patch("subprocess.Popen")
    @patch("time.sleep")
    @patch("teuthology.dispatcher.supervisor.report.try_push_job_info")
    def test_run_with_watchdog_with_reporting(self, m_tpji, m_sleep, m_popen):
        config = {
            "name": "the_name",
            "job_id": "1",
            "archive_path": "archive/path",
            "teuthology_branch": "jewel"
        }
        process = Mock()
        process.poll.return_value = "not None"
        m_proc = Mock()
        m_proc.poll.return_value = "not None"
        m_popen.return_value = m_proc
        supervisor.run_with_watchdog(process, config)
