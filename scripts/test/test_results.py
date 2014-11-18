import docopt

from script import Script
from scripts import results

doc = results.__doc__


class TestResults(Script):
    script_name = 'teuthology-results'

    def test_args(self):
        args = docopt.docopt(doc, [
            "--archive-dir", "some/archive/dir",
            "--name", "the_name",
        ])
        assert args["--archive-dir"] == "some/archive/dir"
        assert args["--name"] == "the_name"
