from script import Script
from scripts.run import parse_args


class TestRun(Script):
    script_name = 'teuthology'
    script_module = 'scripts.run'

    def test_all_args(self):
        args = parse_args([
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
            "--interactive-on-error",
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
        assert args.interactive_on_error
        assert args.config == ["path/to/config.yml"]

    def test_multiple_configs(self):
        args = parse_args([
            "config1.yml",
            "config2.yml",
        ])
        assert args.config == ["config1.yml", "config2.yml"]
