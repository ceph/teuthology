import docopt

from script import Script
from scripts import worker

doc = worker.__doc__


class TestWorker(Script):
    script_name = 'teuthology-worker'

    def test_args(self):
        args = docopt.docopt(doc, [
            "--verbose",
            "--archive-dir=some/archive/dir",
            "-l some/log/dir",
            "-t the_tube",
        ])
        assert args["--verbose"]
        assert args["--archive-dir"] == "some/archive/dir"
        assert args["--log-dir"] == "some/log/dir"
        assert args["--tube"] == "the_tube"
