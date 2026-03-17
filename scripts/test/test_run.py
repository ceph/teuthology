import argparse

from script import Script
from scripts import run


class TestRun(Script):
    script_name = 'teuthology'

    def test_all_args(self):
        # Test that the argument parser works correctly
        parser = argparse.ArgumentParser()
        parser.add_argument('config', nargs='+')
        parser.add_argument('-v', '--verbose', action='store_true')
        parser.add_argument('-a', '--archive')
        parser.add_argument('--description')
        parser.add_argument('--owner')
        parser.add_argument('--lock', action='store_true')
        parser.add_argument('--machine-type')
        parser.add_argument('--os-type')
        parser.add_argument('--os-version')
        parser.add_argument('--block', action='store_true')
        parser.add_argument('--name')
        parser.add_argument('--suite-path')

        args = parser.parse_args([
            "--verbose",
            "--archive", "some/archive/dir",
            "--description", "the_description",
            "--owner", "the_owner",
            "--lock",
            "--machine-type", "machine_type",
            "--os-type", "os_type",
            "--os-version", "os_version",
            "--block",
            "--name", "the_name",
            "--suite-path", "some/suite/dir",
            "path/to/config.yml",
        ])
        assert args.verbose
        assert args.archive == "some/archive/dir"
        assert args.description == "the_description"
        assert args.owner == "the_owner"
        assert args.lock
        assert args.machine_type == "machine_type"
        assert args.os_type == "os_type"
        assert args.os_version == "os_version"
        assert args.block
        assert args.name == "the_name"
        assert args.suite_path == "some/suite/dir"
        assert args.config == ["path/to/config.yml"]

    def test_multiple_configs(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('config', nargs='+')
        args = parser.parse_args([
            "config1.yml",
            "config2.yml",
        ])
        assert args.config == ["config1.yml", "config2.yml"]
