from teuthology.schedule import build_config
from teuthology.misc import get_user
from unittest.mock import patch, Mock
from teuthology import report
from teuthology import schedule

import unittest
import os


class TestSchedule(unittest.TestCase):
    basic_args = {
        '--verbose': False,
        '--owner': 'OWNER',
        '--description': 'DESC',
        '--email': 'EMAIL',
        '--first-in-suite': False,
        '--last-in-suite': True,
        '--name': 'NAME',
        '--worker': 'tala',
        '--timeout': '6',
        '--priority': '99',
        # TODO: make this work regardless of $PWD
        #'<conf_file>': ['../../examples/3node_ceph.yaml',
        #                '../../examples/3node_rgw.yaml'],
        }

    def test_basic(self):
        expected = {
            'description': 'DESC',
            'email': 'EMAIL',
            'first_in_suite': False,
            'last_in_suite': True,
            'machine_type': 'tala',
            'name': 'NAME',
            'owner': 'OWNER',
            'priority': 99,
            'results_timeout': '6',
            'verbose': False,
            'tube': 'tala',
        }

        job_dict = build_config(self.basic_args)
        assert job_dict == expected

    def test_owner(self):
        args = self.basic_args
        args['--owner'] = None
        job_dict = build_config(self.basic_args)
        assert job_dict['owner'] == 'scheduled_%s' % get_user()


    def test_dump_job_to_file(self):
        path = 'teuthology/test/job'
        job_config = {
            'description': 'DESC',
            'email': 'EMAIL',
            'first_in_suite': False,
            'last_in_suite': True,
            'machine_type': 'tala',
            'name': 'NAME',
            'owner': 'OWNER',
            'priority': 99,
            'results_timeout': '6',
            'verbose': False,
            'tube': 'tala',
        }
        schedule.dump_job_to_file(path, job_config)

        count_file_path = path + '.count'
        assert os.path.exists(count_file_path) == True


    def test_mock_create_queue(self):
        mock_get_patcher = patch('teuthology.schedule.report.create_machine_type_queue')
        machine_type = 'test_queue'

        mock_get = mock_get_patcher.start()
        mock_get.return_value = Mock(status_code = 200)

        response = report.create_machine_type_queue(machine_type)

        mock_get_patcher.stop()

        self.assertEqual(response.status_code, 200)
