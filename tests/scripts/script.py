import sys
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
        # docopt
        if module.__doc__ and "usage" in module.__doc__.lower():
            return
        if hasattr(module, "doc") and module.doc and "usage" in module.doc.lower():
            return
        # argparse
        if hasattr(module, "parse_args"):
            with pytest.raises(SystemExit):
                module.parse_args([])
            captured = capsys.readouterr()
            assert "usage: " in captured.err
            return
        # If neither, fail
        raise AssertionError(
            f"{self.script_name} has neither a docstring/doc variable with usage info "
            f"nor a parse_args function"
        )

    def test_invalid(self, module):
        original_argv = sys.argv
        try:
            sys.argv = [self.script_name, "--invalid-option"]
            with pytest.raises(SystemExit):
                if hasattr(module, "parse_args"):
                    module.parse_args(sys.argv[1:])
                elif hasattr(module, "main"):
                    # For docopt-based scripts, main() will call docopt which exits on error
                    module.main()
                else:
                    raise NotImplementedError(
                        f"Don't know how to test {self.script_name}"
                    )
        finally:
            sys.argv = original_argv
