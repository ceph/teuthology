import pytest
from script import Script


class TestUpdatekeys(Script):
    script_name = 'teuthology-updatekeys'
    script_module = 'scripts.updatekeys'

    def test_invalid(self):
        pytest.skip(
            "teuthology.lock needs to be partially refactored to allow "
            "teuthology-updatekeys to return nonzero in all error cases"
        )

    def test_no_args(self, module):
        # machines is nargs='*' so no args is valid; just ensure it parses cleanly
        args = module.parse_args([])
        assert args.machines == []
