from unittest.mock import patch, Mock
from teuthology import report

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
