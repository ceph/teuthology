from teuthology import dispatcher
from unittest.mock import patch, Mock
from teuthology import report

import unittest.mock as mock
import unittest


class TestDispatcher(unittest.TestCase):

    def test_mock_get_queue_job(self):
        mock_get_patcher = patch('teuthology.dispatcher.report.get_queued_job')
        machine_type = 'test_queue'
        job_config = {
            'job_id': '1',
            'description': 'DESC',
            'email': 'EMAIL',
            'first_in_suite': False,
            'last_in_suite': True,
            'machine_type': 'test_queue',
            'name': 'NAME',
            'owner': 'OWNER',
            'priority': 99,
            'results_timeout': '6',
            'verbose': False,
        }

        mock_get = mock_get_patcher.start()
        mock_get.return_value = Mock(status_code = 200)
        mock_get.return_value.json.return_value = job_config

        response = report.get_queued_job(machine_type)

        mock_get_patcher.stop()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), job_config)
    

    @patch("teuthology.worker.fetch_teuthology")
    @patch("teuthology.dispatcher.fetch_qa_suite")
    @patch("teuthology.worker.fetch_qa_suite")
    @patch("teuthology.dispatcher.report.get_queued_job")
    @patch("teuthology.dispatcher.report.try_push_job_info")
    @patch("teuthology.dispatcher.setup_log_file")
    @patch("os.path.isdir")
    @patch("os.getpid")
    @patch("teuthology.dispatcher.teuth_config")
    @patch("subprocess.Popen")
    @patch("os.path.join")
    @patch("teuthology.dispatcher.create_job_archive")
    @patch("yaml.safe_dump")
    def test_dispatcher_main(self, m_fetch_teuthology, m_fetch_qa_suite, 
                             m_worker_fetch_qa_suite, m_get_queued_job, 
                             m_try_push_job_info, 
                             m_setup_log, 
                             m_isdir, m_getpid, 
                             m_t_config, m_popen, m_join, m_create_archive, m_yaml_dump):
            
        args = {
            '--owner': 'the_owner',
            '--archive-dir': '/archive/dir',
            '--log-dir': '/worker/log',
            '--name': 'the_name',
            '--description': 'the_description',
            '--machine-type': 'test_queue',
            '--supervisor': False,
            '--verbose': False,
            '--queue-backend': 'paddles',
            '--exit-on-empty-queue': False
        }

        m = mock.MagicMock()
        job_id = {'job_id': '1'}
        m.__getitem__.side_effect = job_id.__getitem__
        m.__iter__.side_effect = job_id.__iter__
        job = {
            'job_id': '1',
            'description': 'DESC',
            'email': 'EMAIL',
            'first_in_suite': False,
            'last_in_suite': True,
            'machine_type': 'test_queue',
            'name': 'NAME',
            'owner': 'OWNER',
            'priority': 99,
            'results_timeout': '6',
            'verbose': False,
            'stop_worker': True,
            'archive_path': '/archive/dir/NAME/1'
        }

        m_fetch_teuthology.return_value = '/teuth/path'
        m_fetch_qa_suite.return_value = '/suite/path'
        m_isdir.return_value = True
        mock_get_patcher = patch('teuthology.dispatcher.report.get_queued_job')
        mock_get = mock_get_patcher.start()
        mock_get.return_value = job

        mock_prep_job_patcher = patch('teuthology.dispatcher.prep_job')
        mock_prep_job = mock_prep_job_patcher.start()
        mock_prep_job.return_value = (job, '/teuth/bin/path')
        m_yaml_dump.return_value = ''

        m_try_push_job_info.called_once_with(job, dict(status='running'))
        dispatcher.main(args)
        mock_get_patcher.stop()

        
