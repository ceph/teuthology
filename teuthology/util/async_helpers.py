"""Shared asyncio/threading helpers used by synchronous teuthology code.

This module centralizes the small compatibility wrappers that allow legacy
synchronous code paths to schedule work on a dedicated asyncio event loop
running in a background thread.

The helpers here intentionally preserve the behavior expected by the existing
call sites in ``parallel.py``, ``orchestra/run.py``, ``task/lockfile.py``,
``task/proc_thrasher.py``, and ``task/pexec.py``.
"""

from __future__ import annotations

import asyncio
import functools
import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable, Optional, TypeVar, Union

T = TypeVar("T")


class TaskHandle:
    """Wrapper around a thread-safe scheduled coroutine.

    The interface mirrors the subset of the gevent greenlet API used by the
    existing codebase: ``get()`` waits for completion and returns the result,
    while ``kill()`` cancels the underlying future.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, coro):
        self._loop = loop
        self._future: Future = asyncio.run_coroutine_threadsafe(coro, loop)
        self._killed = False

    def get(self, block: bool = True, timeout: Optional[float] = None):
        """Return the coroutine result.

        :param block: Present for API compatibility. The current callers always
            use blocking semantics.
        :param timeout: Optional timeout passed to the underlying future.
        """
        if not block:
            if not self._future.done():
                raise RuntimeError("Result not ready")
            return self._future.result()
        return self._future.result(timeout=timeout)

    def kill(self, block: bool = True):
        """Cancel the scheduled coroutine.

        :param block: If true, briefly wait for cancellation to propagate.
        """
        if not self._killed and not self._future.done():
            self._killed = True
            self._future.cancel()
            if block:
                try:
                    self._future.result(timeout=1.0)
                except Exception:
                    # Expected: CancelledError or other exceptions during cancellation
                    pass

    @property
    def future(self) -> Future:
        """Expose the underlying concurrent future for compatibility."""
        return self._future


class SyncQueue:
    """Thread-safe queue wrapper with a minimal gevent-like API."""

    def __init__(self, maxsize: int = 0):
        self._queue = queue.Queue(maxsize=maxsize)

    def put(self, item: Any):
        """Put an item into the queue, blocking until space is available."""
        self._queue.put(item)

    def get(self):
        """Remove and return an item from the queue, blocking if necessary."""
        return self._queue.get()

    def empty(self) -> bool:
        """Return ``True`` when the queue contains no items."""
        return self._queue.empty()

    def full(self) -> bool:
        """Return ``True`` when the queue has reached ``maxsize``."""
        return self._queue.full()


class SyncEvent:
    """Thread-safe event wrapper with a minimal gevent-like API."""

    def __init__(self):
        self._event = threading.Event()

    def set(self):
        """Set the event and wake waiting threads."""
        self._event.set()

    def clear(self):
        """Clear the event."""
        self._event.clear()

    def wait(self, timeout: Optional[float] = None):
        """Block until the event is set or the timeout expires."""
        return self._event.wait(timeout=timeout)


class EventLoopManager:
    """Manager for a dedicated background asyncio event loop.

    Instances manage one event loop running in one daemon thread. Most call
    sites can create an instance directly when they want isolated lifecycle
    control. ``get_instance()`` provides a shared singleton for modules that
    historically relied on a process-wide loop.
    """

    _instance: Optional["EventLoopManager"] = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = False
        self._state_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "EventLoopManager":
        """Return the process-wide singleton instance."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def start(self):
        """Start the background event loop if it is not already running."""
        if self._started and self._loop is not None and self._loop.is_running():
            return

        with self._state_lock:
            if self._started and self._loop is not None and self._loop.is_running():
                return

            self._loop = asyncio.new_event_loop()

            def run_loop():
                assert self._loop is not None
                asyncio.set_event_loop(self._loop)
                self._loop.run_forever()

            self._thread = threading.Thread(target=run_loop, daemon=True)
            self._thread.start()
            self._started = True

    def stop(self, join_timeout: float = 1.0, close_loop: bool = True):
        """Stop the background event loop.

        :param join_timeout: Maximum time to wait for the loop thread to exit.
        :param close_loop: Close the loop object after the thread stops. This is
            useful for call sites that historically owned a short-lived loop.
            Defaults to True to prevent resource warnings.
        """
        with self._state_lock:
            loop = self._loop
            thread = self._thread

            if loop and loop.is_running():
                # Cancel all pending tasks and wait for them to complete
                async def cancel_and_wait():
                    tasks = [task for task in asyncio.all_tasks(loop)
                            if not task.done() and task is not asyncio.current_task(loop)]
                    for task in tasks:
                        task.cancel()
                    # Wait for all tasks to be cancelled
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
                
                # Schedule the cancellation and wait for it to complete
                future = asyncio.run_coroutine_threadsafe(cancel_and_wait(), loop)
                try:
                    future.result(timeout=0.5)
                except Exception:
                    pass
                
                loop.call_soon_threadsafe(loop.stop)
            if thread and thread.is_alive():
                thread.join(timeout=join_timeout)
            if close_loop and loop and not loop.is_closed():
                loop.close()

            self._started = False
            self._loop = None
            self._thread = None

    def get_loop(self) -> asyncio.AbstractEventLoop:
        """Return the managed event loop, starting it if necessary."""
        self.start()
        assert self._loop is not None
        return self._loop

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Property alias for ``get_loop()``."""
        return self.get_loop()

    @property
    def thread(self) -> Optional[threading.Thread]:
        """Return the loop thread, if started."""
        return self._thread

    @property
    def started(self) -> bool:
        """Return whether the manager currently considers the loop started."""
        return self._started

    def submit(self, coro) -> Future:
        """Schedule a coroutine on the managed loop and return its future."""
        return asyncio.run_coroutine_threadsafe(coro, self.get_loop())

    def create_task_handle(self, coro) -> TaskHandle:
        """Schedule a coroutine and return a ``TaskHandle`` wrapper."""
        return TaskHandle(self.get_loop(), coro)

    def spawn(self, func: Callable[..., T], *args, **kwargs) -> TaskHandle:
        """Run a synchronous callable in the loop's default executor.

        This preserves the behavior of the previous ``spawn()`` helpers used by
        ``lockfile.py`` and similar modules.
        """

        async def run_in_executor():
            loop = asyncio.get_event_loop()
            wrapped = functools.partial(func, *args, **kwargs)
            return await loop.run_in_executor(None, wrapped)

        return self.create_task_handle(run_in_executor())

    def run_sync(self, func: Callable[..., T], *args, **kwargs) -> Future:
        """Submit a synchronous callable to the loop executor."""
        async def run_in_executor():
            loop = asyncio.get_event_loop()
            wrapped = functools.partial(func, *args, **kwargs)
            return await loop.run_in_executor(None, wrapped)

        return self.submit(run_in_executor())


def start_event_loop() -> EventLoopManager:
    """Start and return the shared event loop manager."""
    manager = EventLoopManager.get_instance()
    manager.start()
    return manager


__all__ = [
    "EventLoopManager",
    "SyncEvent",
    "SyncQueue",
    "TaskHandle",
    "start_event_loop",
]

# Made with Bob
