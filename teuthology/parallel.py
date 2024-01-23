import asyncio
import logging

from typing import List


log = logging.getLogger(__name__)


class parallel(object):
    """
    This class is a context manager for running functions in parallel.

    You add functions to be run with the spawn method::

        async with parallel() as p:
            for foo in bar:
                p.spawn(quux, foo, baz=True)

    You can iterate over the results (which are in arbitrary order)::

        async with parallel() as p:
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
        # self.results = asyncio.Queue()
        self.results = []
        self.count = 0
        self.iteration_stopped = False
        self.tasks: List[asyncio.Task] = []
        self.any_spawned = False

    def spawn(self, func, *args, **kwargs):
        self.any_spawned = True
        self.count += 1
        async def wrapper():
            # print(f"{func} {args} {kwargs}")
            return func(*args, **kwargs)
        self.tasks.append(asyncio.create_task(
            wrapper()
        ))

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_value is not None:
            return False
        self.results = await asyncio.gather(*self.tasks)#, return_exceptions=True)

        return True

    def __aiter__(self):
        return self

    async def __anext__(self):
        print(f"tasks={self.tasks}")
        if not self.tasks:
            raise StopAsyncIteration
        task = self.tasks.pop(0)
        res = await task
        print(f"res={res}")
        return res
