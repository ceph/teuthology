import pytest

from teuthology import beanstalk


class DummyConnection:
    def __init__(self, tubes_list):
        self._tubes = tubes_list
        self.paused = []

    def tubes(self):
        return list(self._tubes)

    def pause_tube(self, tube, duration):
        self.paused.append((tube, duration))


def test_pause_tube_filters_none_and_pauses_only_strings():
    conn = DummyConnection([None, 'alpha', 'beta'])
    beanstalk.pause_tube(conn, tube=None, duration=5)
    # Only 'alpha' and 'beta' should be paused (None ignored)
    assert ('alpha', 5) in conn.paused
    assert ('beta', 5) in conn.paused
    assert all(isinstance(t, str) for t, _ in conn.paused)


def test_pause_tube_with_specific_tube():
    conn = DummyConnection(['x', 'y'])
    beanstalk.pause_tube(conn, tube='x', duration=0)
    assert conn.paused == [('x', 0)]
