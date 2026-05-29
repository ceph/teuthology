"""
Process thrasher
"""
import asyncio
import logging
import random
import threading
import time
from concurrent.futures import Future
from typing import Optional, Union

from teuthology.orchestra import run

log = logging.getLogger(__name__)

class ProcThrasher:
    """ Kills and restarts some number of the specified process on the specified
        remote
    """
    def __init__(self, config, remote, *proc_args, **proc_kwargs):
        self.proc_kwargs = proc_kwargs
        self.proc_args = proc_args
        self.config = config
        self._task: Optional[Union[asyncio.Task, Future]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._started = False
        self.logger = proc_kwargs.get("logger", log.getChild('proc_thrasher'))
        self.remote = remote

        # config:
        self.num_procs = self.config.get("num_procs", 5)
        self.rest_period = self.config.get("rest_period", 100) # seconds
        self.run_time = self.config.get("run_time", 1000) # seconds

    def log(self, msg):
        """
        Local log wrapper
        """
        self.logger.info(msg)

    def _start_event_loop(self):
        """Start a dedicated event loop in a background thread."""
        if self._started:
            return
        
        self._started = True
        self._loop = asyncio.new_event_loop()
        
        def run_loop():
            assert self._loop is not None
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()
        
        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()

    def start(self):
        """
        Start thrasher.  This maintains the synchronous interface while
        using asyncio internally.
        """
        if self._task is not None:
            return
        
        if not self._started:
            self._start_event_loop()
        
        assert self._loop is not None
        # Schedule the loop coroutine as a task in the event loop
        self._task = asyncio.run_coroutine_threadsafe(
            self._async_loop(),
            self._loop
        )

    def join(self):
        """
        Wait for the thrasher to complete.
        """
        if self._task is None:
            return
        
        try:
            # Wait for the task to complete
            self._task.result()
        except Exception:
            # Re-raise any exception from the task
            raise
        finally:
            self._cleanup()

    def _cleanup(self):
        """Clean up the event loop and thread."""
        if self._loop:
            # Stop the event loop
            if self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            # Give it a moment to stop
            if self._loop_thread and self._loop_thread.is_alive():
                self._loop_thread.join(timeout=2.0)
            # Close the loop
            if not self._loop.is_closed():
                self._loop.close()

    async def _async_loop(self):
        """
        Thrashing loop -- loops at time intervals.  Inside that loop, the
        code loops through the individual procs, creating new procs.
        
        This is the async version that runs in the event loop.
        """
        time_started = time.time()
        procs = []
        self.log("Starting")
        
        loop = asyncio.get_event_loop()
        
        while time_started + self.run_time > time.time():
            if len(procs) > 0:
                self.log("Killing proc")
                proc = random.choice(procs)
                procs.remove(proc)
                
                # Run synchronous operations in executor
                await loop.run_in_executor(None, proc.stdin.close)
                self.log("About to wait")
                await loop.run_in_executor(None, run.wait, [proc])
                self.log("Killed proc")
                
            while len(procs) < self.num_procs:
                self.log("Creating proc " + str(len(procs) + 1))
                self.log("args are " + str(self.proc_args) + " kwargs: " + str(self.proc_kwargs))
                
                # Run remote.run in executor since it's synchronous
                proc = await loop.run_in_executor(
                    None,
                    self.remote.run,
                    *self.proc_args,
                    **self.proc_kwargs
                )
                procs.append(proc)
            
            self.log("About to sleep")
            await asyncio.sleep(self.rest_period)
            self.log("Just woke")

        # Wait for all remaining processes
        if procs:
            await loop.run_in_executor(None, run.wait, procs)

# Made with Bob
