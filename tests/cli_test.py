import pytest
from importlib import import_module


class CliTest(object):
    """
    Base class for CLI tests for migrated teuthology.<name>.cli scripts.
    Subclasses set cli_name (e.g. 'teuthology-schedule').
    """
    cli_name = "teuthology"

    @pytest.fixture(scope="class")
    def module(self):
        # 'teuthology-suite' -> 'suite', 'teuthology' -> 'run'
        name = self.cli_name.replace("teuthology-", "").replace("teuthology", "run")
        return import_module(f"teuthology.{name}.cli")

    @pytest.fixture(scope="class")
    def parser(self, module):
        return module.make_parser()

    def test_help(self, capsys: pytest.CaptureFixture[str], module):
        with pytest.raises(SystemExit):
            module.make_parser().parse_args([])
        assert "usage: " in capsys.readouterr().err
