import asyncio
import functools
import logging
import sys
from typing import Any, Callable, Optional



log = logging.getLogger(__name__)


class ExceptionHolder(object):
    def __init__(self, exc_info):
        self.exc_info = exc_info


def capture_traceback(func, *args, **kwargs):
    """
    Utility function to capture tracebacks of any exception func
    raises.
    """
    try:
        return func(*args, **kwargs)
    except Exception:
        return ExceptionHolder(sys.exc_info())


def resurrect_traceback(exc):
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

    def __init__(self):
        self.count = 0
        self.any_spawned = False
        self.iteration_stopped = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tasks = set()
        self._results_queue: Optional[asyncio.Queue] = None
        self._started = False

    def _start_event_loop(self):
        """Start a dedicated event loop in a background thread."""
        if self._started:
            return

        self._started = True
        self._loop = asyncio.new_event_loop()
        self._results_queue = asyncio.Queue()

        def run_loop():
            assert self._loop is not None
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        import threading
        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()

    def spawn(self, func: Callable, *args, **kwargs):
        """Spawn a function to run in parallel."""
        if not self._started:
            self._start_event_loop()
        
        assert self._loop is not None
        self.count += 1
        self.any_spawned = True
        
        # Schedule the task in the event loop
        future = asyncio.run_coroutine_threadsafe(
            self._run_task(func, *args, **kwargs),
            self._loop
        )
        self._tasks.add(future)

    async def _run_task(self, func: Callable, *args, **kwargs):
        """Run a synchronous function in the executor and handle its result."""
        try:
            # Run the sync function in a thread pool executor
            loop = asyncio.get_event_loop()
            # We need to use functools.partial to properly pass args and kwargs
            wrapped_func = functools.partial(capture_traceback, func, *args, **kwargs)
            result = await loop.run_in_executor(None, wrapped_func)
            await self._finish(result, None)
        except Exception as e:
            await self._finish(None, e)

    async def _finish(self, result: Any, exception: Optional[Exception]):
        """Handle task completion."""
        assert self._results_queue is not None
        if exception is not None:
            await self._results_queue.put(exception)
        else:
            await self._results_queue.put(result)
        
        self.count -= 1
        if self.count <= 0:
            await self._results_queue.put(StopIteration())

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        if value is not None:
            self._cleanup()
            return False

        # raises if any tasks exited with an exception
        for result in self:
            log.debug('result is %s', repr(result))

        self._cleanup()
        return True

    def _cleanup(self):
        """Clean up the event loop and thread."""
        self._tasks.clear()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if getattr(self, "_loop_thread", None) and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=1.0)

    def __iter__(self):
        return self

    def __next__(self):
        if not self.any_spawned or self.iteration_stopped:
            raise StopIteration()
        
        assert self._loop is not None
        assert self._results_queue is not None
        
        # Get result from async queue synchronously
        future = asyncio.run_coroutine_threadsafe(
            self._results_queue.get(),
            self._loop
        )
        result = future.result()

        try:
            resurrect_traceback(result)
        except StopIteration:
            self.iteration_stopped = True
            raise

        return result

    next = __next__

# Made with Bob
