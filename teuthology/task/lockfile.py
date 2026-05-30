"""
Locking tests
"""
import asyncio
import functools
import logging
import os
import threading
import time
from typing import Optional

from teuthology.orchestra import run
from teuthology import misc as teuthology


log = logging.getLogger(__name__)


class _AsyncTimeout:
    """
    Asyncio-based timeout context manager compatible with gevent.Timeout API.
    """
    def __init__(self, seconds: Optional[float] = None):
        self.seconds = seconds
        self._task: Optional[asyncio.Task] = None
        self._cancelled = False
    
    def start(self):
        """Start the timeout (no-op for compatibility)."""
        pass
    
    def cancel(self):
        """Cancel the timeout."""
        self._cancelled = True
        if self._task and not self._task.done():
            self._task.cancel()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.cancel()
        return False


class _TaskHandle:
    """
    Handle for managing an async task, compatible with gevent greenlet API.
    """
    def __init__(self, loop: asyncio.AbstractEventLoop, coro):
        self._loop = loop
        self._future = asyncio.run_coroutine_threadsafe(coro, loop)
        self._killed = False
    
    def get(self):
        """Wait for and return the task result (blocking)."""
        try:
            return self._future.result()
        except Exception:
            raise
    
    def kill(self, block=True):
        """Kill the task."""
        if not self._killed and not self._future.done():
            self._killed = True
            self._future.cancel()
            if block:
                try:
                    self._future.result(timeout=1.0)
                except Exception:
                    pass


class _EventLoopManager:
    """
    Manages a dedicated event loop in a background thread for async operations.
    """
    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = False
    
    def start(self):
        """Start the event loop in a background thread."""
        if self._started:
            return
        
        self._started = True
        self._loop = asyncio.new_event_loop()
        
        def run_loop():
            assert self._loop is not None
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()
        
        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop the event loop and thread."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._started = False
    
    def spawn(self, func, *args, **kwargs):
        """Spawn a function to run asynchronously."""
        if not self._started:
            self.start()
        assert self._loop is not None
        
        # Wrap the sync function to run in executor
        async def run_in_executor():
            loop = asyncio.get_event_loop()
            wrapped = functools.partial(func, *args, **kwargs)
            return await loop.run_in_executor(None, wrapped)
        
        return _TaskHandle(self._loop, run_in_executor())
    
    @property
    def loop(self):
        """Get the event loop."""
        return self._loop

def task(ctx, config):
    """
    This task is designed to test locking. It runs an executable
    for each lock attempt you specify, at 0.01 second intervals (to
    preserve ordering of the locks).
    You can also introduce longer intervals by setting an entry
    as a number of seconds, rather than the lock dictionary.
    The config is a list of dictionaries. For each entry in the list, you
    must name the "client" to run on, the "file" to lock, and
    the "holdtime" to hold the lock.
    Optional entries are the "offset" and "length" of the lock. You can also specify a
    "maxwait" timeout period which fails if the executable takes longer
    to complete, and an "expectfail".

    An example::

        tasks:
        - ceph:
        - ceph-fuse: [client.0, client.1]
        - lockfile:
          [{client:client.0, file:testfile, holdtime:10},
          {client:client.1, file:testfile, holdtime:0, maxwait:0, expectfail:true},
          {client:client.1, file:testfile, holdtime:0, maxwait:15, expectfail:false},
          10,
          {client: client.1, lockfile: testfile, holdtime: 5},
          {client: client.2, lockfile: testfile, holdtime: 5, maxwait: 1, expectfail: True}]


    In the past this test would have failed; there was a bug where waitlocks weren't
    cleaned up if the process failed. More involved scenarios are also possible.

    :param ctx: Context
    :param config: Configuration
    """
    log.info('Starting lockfile')
    lock_procs = list()
    loop_manager = None
    clients = set()
    testdir = None
    
    try:
        assert isinstance(config, list), \
            "task lockfile got invalid config"

        log.info("building executable on each host")
        buildprocs = list()
        # build the locker executable on each client
        clients_list = list()
        files = list()
        for op in config:
            if not isinstance(op, dict):
                continue
            log.info("got an op")
            log.info("op['client'] = %s", op['client'])
            clients_list.append(op['client'])
            files.append(op['lockfile'])
            if not "expectfail" in op:
                op["expectfail"] = False
            badconfig = False
            if not "client" in op:
                badconfig = True
            if not "lockfile" in op:
                badconfig = True
            if not "holdtime" in op:
                badconfig = True
            if badconfig:
                raise KeyError("bad config {op_}".format(op_=op))

        testdir = teuthology.get_testdir(ctx)
        clients = set(clients_list)
        files = set(files)
        for client in clients:
            (client_remote,) = ctx.cluster.only(client).remotes.keys()
            log.info("got a client remote")
            (_, _, client_id) = client.partition('.')

            proc = client_remote.run(
                args=[
                    'mkdir', '-p', '{tdir}/archive/lockfile'.format(tdir=testdir),
                    run.Raw('&&'),
                    'mkdir', '-p', '{tdir}/lockfile'.format(tdir=testdir),
                    run.Raw('&&'),
                    'wget',
                    '-nv',
                    '--no-check-certificate',
                    'https://raw.github.com/gregsfortytwo/FileLocker/main/sclockandhold.cpp',
                    '-O', '{tdir}/lockfile/sclockandhold.cpp'.format(tdir=testdir),
                    run.Raw('&&'),
                    'g++', '{tdir}/lockfile/sclockandhold.cpp'.format(tdir=testdir),
                    '-o', '{tdir}/lockfile/sclockandhold'.format(tdir=testdir)
                    ],
                logger=log.getChild('lockfile_client.{id}'.format(id=client_id)),
                wait=False
                )
            log.info('building sclockandhold on client{id}'.format(id=client_id))
            buildprocs.append(proc)

        # wait for builds to finish
        run.wait(buildprocs)
        log.info('finished building sclockandhold on all clients')

        # create the files to run these locks on
        client = clients.pop()
        clients.add(client)
        (client_remote,) = ctx.cluster.only(client).remotes.keys()
        (_, _, client_id) = client.partition('.')
        file_procs = list()
        for lockfile in files:
            filepath = os.path.join(testdir, 'mnt.{id}'.format(id=client_id), lockfile)
            proc = client_remote.run(
                args=[
                    'sudo',
                    'touch',
                    filepath,
                    ],
                logger=log.getChild('lockfile_createfile'),
                wait=False
                )
            file_procs.append(proc)
        run.wait(file_procs)
        file_procs = list()
        for lockfile in files:
            filepath = os.path.join(testdir, 'mnt.{id}'.format(id=client_id), lockfile)
            proc = client_remote.run(
                args=[
                    'sudo', 'chown', 'ubuntu.ubuntu', filepath
                    ],
                logger=log.getChild('lockfile_createfile'),
                wait=False
                )
            file_procs.append(proc)
        run.wait(file_procs)
        log.debug('created files to lock')

        # Create event loop manager for async operations
        loop_manager = _EventLoopManager()
        
        # now actually run the locktests
        for op in config:
            if not isinstance(op, dict):
                assert isinstance(op, int) or isinstance(op, float)
                log.info("sleeping for {sleep} seconds".format(sleep=op))
                time.sleep(op)
                continue
            task_handle = loop_manager.spawn(lock_one, op, ctx)
            lock_procs.append((task_handle, op))
            time.sleep(0.1) # to provide proper ordering
        #for op in config

        for (task_handle, op) in lock_procs:
            log.debug('checking lock for op {op_}'.format(op_=op))
            result = task_handle.get()
            if not result:
                raise Exception("Got wrong result for op {op_}".format(op_=op))
        # for (task_handle, op) in lock_procs

    finally:
        #cleanup!
        if lock_procs:
            for (task_handle, op) in lock_procs:
                log.debug('closing proc for op {op_}'.format(op_=op))
                task_handle.kill(block=True)
        
        # Stop the event loop
        if loop_manager:
            loop_manager.stop()

        if clients and testdir:
            for client in clients:
                (client_remote,)  = ctx.cluster.only(client).remotes.keys()
                (_, _, client_id) = client.partition('.')
                # Use the first lockfile from files for cleanup
                for lockfile in files:
                    filepath = os.path.join(testdir, 'mnt.{id}'.format(id=client_id), lockfile)
                    proc = client_remote.run(
                        args=[
                            'rm', '-rf', '{tdir}/lockfile'.format(tdir=testdir),
                            run.Raw(';'),
                            'sudo', 'rm', '-rf', filepath
                            ],
                        wait=True
                        ) #proc
                    break  # Only need to clean up once per client
    #done!
# task

def lock_one(op, ctx):
    """
    Perform the individual lock
    """
    log.debug('spinning up locker with op={op_}'.format(op_=op))
    timeout_obj = None
    proc = None
    result = None
    (client_remote,)  = ctx.cluster.only(op['client']).remotes.keys()
    (_, _, client_id) = op['client'].partition('.')
    testdir = teuthology.get_testdir(ctx)
    filepath = os.path.join(testdir, 'mnt.{id}'.format(id=client_id), op["lockfile"])

    if "maxwait" in op:
        timeout_obj = _AsyncTimeout(seconds=float(op["maxwait"]))
        timeout_obj.start()
    
    timeout_occurred = False
    try:
        proc = client_remote.run(
            args=[
                'adjust-ulimits',
                'ceph-coverage',
                '{tdir}/archive/coverage'.format(tdir=testdir),
                'daemon-helper',
                'kill',
                '{tdir}/lockfile/sclockandhold'.format(tdir=testdir),
                filepath,
                '{holdtime}'.format(holdtime=op["holdtime"]),
                '{offset}'.format(offset=op.get("offset", '0')),
                '{length}'.format(length=op.get("length", '1')),
                ],
            logger=log.getChild('lockfile_client.{id}'.format(id=client_id)),
            wait=False,
            stdin=run.PIPE,
            check_status=False
            )
        
        # Wait for process with timeout
        if timeout_obj and timeout_obj.seconds:
            import signal
            
            def timeout_handler(signum, frame):
                raise TimeoutError("Operation timed out")
            
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(int(timeout_obj.seconds))
            try:
                result = proc.wait()
                signal.alarm(0)  # Cancel alarm
            except TimeoutError:
                timeout_occurred = True
                signal.alarm(0)  # Cancel alarm
                if bool(op["expectfail"]):
                    result = 1
            finally:
                signal.signal(signal.SIGALRM, old_handler)
        else:
            result = proc.wait()
        
        if timeout_occurred:
            if result == 1:
                if bool(op["expectfail"]):
                    log.info("failed as expected for op {op_}".format(op_=op))
                else:
                    raise Exception("Unexpectedly failed to lock {op_} within given timeout!".format(op_=op))
    finally: #clean up proc
        if timeout_obj is not None:
            timeout_obj.cancel()
        if proc is not None:
            proc.stdin.close()

    ret = (result == 0 and not bool(op["expectfail"])) or (result == 1 and bool(op["expectfail"]))

    return ret  #we made it through
