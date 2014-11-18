import docopt

from script import Script
from scripts import suite


class TestSuite(Script):
    script_name = 'teuthology-suite'

    def test_args(self):
        args = docopt.docopt(
            suite.doc,
            "--suite the_suite -t the_branch"
        )
        assert args['--suite'] == "the_suite"
        assert args['--teuthology-branch'] == "the_branch"
