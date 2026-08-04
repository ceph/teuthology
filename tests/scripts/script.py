import pytest
from importlib import import_module


class Script(object):
    script_name = "teuthology"
    script_module = None  # Override in subclasses, e.g., 'scripts.run'

    @pytest.fixture(scope="class")
    def module_name(self) -> str:
        # e.g., 'teuthology-dispatcher' -> 'scripts.dispatcher'
        return self.script_name.replace("teuthology-", "").replace("teuthology", "run")

    @pytest.fixture(scope="class")
    def module(self, module_name):
        return import_module(self.script_module or f"scripts.{module_name}")

    def test_help(self, capsys: pytest.CaptureFixture[str], module):
        assert hasattr(module, "parse_args"), (
            f"{self.script_name} does not expose a parse_args() function"
        )
        with pytest.raises(SystemExit):
            module.parse_args(["--help"])
        captured = capsys.readouterr()
        assert "usage: " in captured.out

    def test_invalid(self, module):
        assert hasattr(module, "parse_args"), (
            f"{self.script_name} does not expose a parse_args() function"
        )
        with pytest.raises(SystemExit):
            module.parse_args(["--invalid-option"])
