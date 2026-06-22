import pytest

from datetime import datetime, timedelta, timezone
from typing import Type

from teuthology.util import time


@pytest.mark.parametrize(
    ["timestamp", "result"],
    [
        ["1999-12-31_23:59:59", datetime(1999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)],
        ["1999-12-31_23:59", datetime(1999, 12, 31, 23, 59, 0, tzinfo=timezone.utc)],
        ["1999-12-31T23:59:59", datetime(1999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)],
        ["1999-12-31T23:59:59+00:00", datetime(1999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)],
        ["1999-12-31T17:59:59-06:00", datetime(1999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)],
        ["2024-01-01", datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)],
        ["tomorrow", ValueError],
        ["1d", ValueError],
        ["", ValueError],
        ["2024", ValueError],

    ]
)
def test_parse_timestamp(timestamp: str, result: datetime | Type[Exception]):
    if isinstance(result, datetime):
        assert time.parse_timestamp(timestamp) == result
    else:
        with pytest.raises(result):
            time.parse_timestamp(timestamp)


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
