import importlib
import pytest
import sys

from pathlib import Path
from typing import List

root = Path("./teuthology")


def find_modules() -> List[str]:
    modules = []
    for path in root.rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        if "-" in path.name:
            continue
        if path.name == "__init__.py":
            path = path.parent

        path_name = str(path).replace("/", ".")
        if path_name.endswith(".py"):
            path_name = path_name[:-3]
        modules.append(path_name)
    return sorted(modules)


@pytest.mark.parametrize("module", find_modules())
def test_import_modules(module):
    importlib.import_module(module)
    assert module in sys.modules
