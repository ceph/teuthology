from teuthology.schedule import build_config
from teuthology.schedule.cli import make_parser
from teuthology.misc import get_user
from tests.cli_test import CliTest


class TestSchedule(CliTest):
    script_name = 'teuthology-schedule'
    argv = [
        '--name', 'NAME',
        '--owner', 'OWNER',
        '--description', 'DESC',
        '--email', 'EMAIL',
        '--last-in-suite',
        '--worker', 'tala',
        '--timeout', '6',
        '--priority', '99',
        # TODO: make this work regardless of $PWD
        #'<conf_file>': ['../../examples/3node_ceph.yaml',
        #                '../../examples/3node_rgw.yaml'],
    ]

    def test_basic(self):
        args = make_parser().parse_args(self.argv).__dict__
        expected = {
            'description': 'DESC',
            'email': 'EMAIL',
            'first_in_suite': False,
            'last_in_suite': True,
            'machine_type': 'tala',
            'name': 'NAME',
            'owner': 'OWNER',
            'priority': 99,
            'results_timeout': 6,
            'verbose': False,
            'tube': 'tala',
        }

        job_dict = build_config(args)
        assert job_dict == expected

    def test_owner(self):
        argv = list(self.argv)
        if '--owner' in argv:
            idx = argv.index('--owner')
            argv.pop(idx)   # remove --owner flag
            argv.pop(idx)   # remove its value
        args = make_parser().parse_args(argv).__dict__
        job_dict = build_config(args)
        assert job_dict['owner'] == 'scheduled_%s' % get_user()

