import argparse

from script import Script
from scripts import ls


class TestLs(Script):
    script_name = 'teuthology-ls'

    def test_args(self):
        # Test that the argument parser works correctly
        parser = argparse.ArgumentParser()
        parser.add_argument('archive_dir')
        parser.add_argument('-v', '--verbose', action='store_true')
        args = parser.parse_args(["--verbose", "some/archive/dir"])
        assert args.verbose
        assert args.archive_dir == "some/archive/dir"
