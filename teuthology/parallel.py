import logging
import sys
from typing import Callable, Iterator, Optional
from types import TracebackType

import gevent
import gevent.pool
import gevent.queue


log = logging.getLogger(__name__)


class ExceptionHolder(object):
    def __init__(self, exc_info: tuple[type[BaseException], BaseException, TracebackType]) -> None:
        self.exc_info = exc_info


def capture_traceback(func: Callable, *args, **kwargs):
    """
    Utility function to capture tracebacks of any exception func
    raises.
    """
    try:
        return func(*args, **kwargs)
    except Exception:
        return ExceptionHolder(sys.exc_info())


def resurrect_traceback(exc) -> None:
    if isinstance(exc, ExceptionHolder):
        raise exc.exc_info[1]
    elif isinstance(exc, BaseException):
        raise exc
    else:
        return


class parallel(object):
    """
    This class is a context manager for running functions in parallel.

    You add functions to be run with the spawn method::

        with parallel() as p:
            for foo in bar:
                p.spawn(quux, foo, baz=True)

    You can iterate over the results (which are in arbitrary order)::

        with parallel() as p:
            for foo in bar:
                p.spawn(quux, foo, baz=True)
            for result in p:
                print(result)

    If one of the spawned functions throws an exception, it will be thrown
    when iterating over the results, or when the with block ends.

    At the end of the with block, the main thread waits until all
    spawned functions have completed, or, if one exited with an exception,
    kills the rest and raises the exception.
    """

    def __init__(self) -> None:
        self.group = gevent.pool.Group()
        self.results = gevent.queue.Queue()
        self.count = 0
        self.any_spawned = False
        self.iteration_stopped = False

    def spawn(self, func: Callable, *args, **kwargs) -> None:
        self.count += 1
        self.any_spawned = True
        greenlet = self.group.spawn(capture_traceback, func, *args, **kwargs)
        greenlet.link(self._finish)

    def __enter__(self) -> 'parallel':
        return self

    def __exit__(self, type_: Optional[type[BaseException]], value: Optional[BaseException], traceback: Optional[TracebackType]) -> bool:
        if value is not None:
            return False

        # raises if any greenlets exited with an exception
        for result in self:
            log.debug('result is %s', repr(result))

        return True

    def __iter__(self) -> Iterator:
        return self

    def __next__(self):
        if not self.any_spawned or self.iteration_stopped:
            raise StopIteration()
        result = self.results.get()

        try:
            resurrect_traceback(result)
        except StopIteration:
            self.iteration_stopped = True
            raise

        return result

    next = __next__

    def _finish(self, greenlet: gevent.Greenlet) -> None:
        if greenlet.successful():
            self.results.put(greenlet.value)
        else:
            self.results.put(greenlet.exception)

        self.count -= 1
        if self.count <= 0:
            self.results.put(StopIteration())
