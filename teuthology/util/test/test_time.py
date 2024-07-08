import pytest

from datetime import timedelta
from typing import Type

from teuthology.util import time


@pytest.mark.parametrize(
    ["offset", "result"],
    [
        ["1s", timedelta(seconds=1)],
        ["1m", timedelta(minutes=1)],
        ["1h", timedelta(hours=1)],
        ["1d", timedelta(days=1)],
        ["1w", timedelta(weeks=1)],
        ["365d", timedelta(days=365)],
        ["1x", ValueError],
        ["-1m", ValueError],
        ["0xde", ValueError],
        ["frog", ValueError],
        ["7dwarfs", ValueError],
    ]
)
def test_parse_offset(offset: str, result: timedelta | Type[Exception]):
    if isinstance(result, timedelta):
        assert time.parse_offset(offset) == result
    else:
        with pytest.raises(result):
            time.parse_offset(offset)
