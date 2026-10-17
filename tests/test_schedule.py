from teuthology.schedule import build_config
from teuthology.misc import get_user


class TestSchedule(object):
    basic_kwargs = dict(
        name='NAME',
        description='DESC',
        owner='OWNER',
        worker='tala',
        priority='99',
        first_in_suite=False,
        last_in_suite=True,
        email='EMAIL',
        verbose=False,
        timeout='6',
    )

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

        job_dict = build_config({}, **self.basic_kwargs)
        assert job_dict == expected

    def test_owner(self):
        kwargs = dict(self.basic_kwargs, owner=None)
        job_dict = build_config({}, **kwargs)
        assert job_dict['owner'] == 'scheduled_%s' % get_user()

