"""
Handle parallel execution on remote hosts
"""
import logging
import queue
import threading

from teuthology import misc as teuthology
from teuthology.parallel import parallel
from teuthology.orchestra import run as tor

log = logging.getLogger(__name__)


class _SyncQueue:
    """
    Thread-safe queue using standard library queue.Queue.
    Compatible with gevent.queue.Queue API for barrier synchronization.
    """
    def __init__(self, maxsize: int = 0):
        self._queue = queue.Queue(maxsize=maxsize)
    
    def put(self, item):
        """Put an item into the queue (blocking)."""
        self._queue.put(item)
    
    def get(self):
        """Get an item from the queue (blocking)."""
        return self._queue.get()
    
    def empty(self) -> bool:
        """Return True if the queue is empty."""
        return self._queue.empty()
    
    def full(self) -> bool:
        """Return True if the queue is full."""
        return self._queue.full()


class _SyncEvent:
    """
    Thread-safe event using standard library threading.Event.
    Compatible with gevent.event.Event API for barrier synchronization.
    """
    def __init__(self):
        self._event = threading.Event()
    
    def set(self):
        """Set the event."""
        self._event.set()
    
    def clear(self):
        """Clear the event."""
        self._event.clear()
    
    def wait(self, timeout=None):
        """Wait for the event to be set (blocking)."""
        return self._event.wait(timeout=timeout)


def _init_barrier(barrier_queue, remote):
    """current just queues a remote host""" 
    barrier_queue.put(remote)

def _do_barrier(barrier, barrier_queue, remote):
    """special case for barrier"""
    barrier_queue.get()
    if barrier_queue.empty():
        barrier.set()
        barrier.clear()
    else:
        barrier.wait()

    barrier_queue.put(remote)
    if barrier_queue.full():
        barrier.set()
        barrier.clear()
    else:
        barrier.wait()

def _exec_host(barrier, barrier_queue, remote, sudo, testdir, ls):
    """Execute command remotely"""
    args = [
        'TESTDIR={tdir}'.format(tdir=testdir),
        'bash',
        '-s'
        ]
    if sudo:
        args.insert(0, 'sudo')
    
    r = remote.run( args=args, stdin=tor.PIPE, wait=False)
    r.stdin.writelines(['set -e\n'])
    r.stdin.flush()
    for l in ls:
        l.replace('$TESTDIR', testdir)
        if l == "barrier":
            _do_barrier(barrier, barrier_queue, remote)
            continue

        r.stdin.writelines([l, '\n'])
        r.stdin.flush()
    r.stdin.writelines(['\n'])
    r.stdin.flush()
    r.stdin.close()
    log.info('Running commands on host %s', remote.name)
    for l in ls:
        log.info('%s', l)
    tor.wait([r])

def _generate_remotes(ctx, config):
    """Return remote roles and the type of role specified in config"""
    if 'all' in config and len(config) == 1:
        ls = config['all']
        for remote in ctx.cluster.remotes.keys():
            yield (remote, ls)
    elif 'clients' in config:
        ls = config['clients']
        for role in teuthology.all_roles_of_type(ctx.cluster, 'client'):
            (remote,) = ctx.cluster.only('client.{r}'.format(r=role)).remotes.keys()
            yield (remote, ls)
        del config['clients']
        for role, ls in config.items():
            (remote,) = ctx.cluster.only(role).remotes.keys()
            yield (remote, ls)
    else:
        for role, ls in config.items():
            (remote,) = ctx.cluster.only(role).remotes.keys()
            yield (remote, ls)

def task(ctx, config):
    """
    Execute commands on multiple hosts in parallel

        tasks:
        - ceph:
        - ceph-fuse: [client.0, client.1]
        - pexec:
            client.0:
              - while true; do echo foo >> bar; done
            client.1:
              - sleep 1
              - tail -f bar
        - interactive:

    Execute commands on all hosts in the cluster in parallel.  This
    is useful if there are many hosts and you want to run the same
    command on all:

        tasks:
        - pexec:
            all:
              - grep FAIL /var/log/ceph/*

    Or if you want to run in parallel on all clients:

        tasks:
        - pexec:
            clients:
              - dd if=/dev/zero of={testdir}/mnt.* count=1024 bs=1024

    You can also ensure that parallel commands are synchronized with the
    special 'barrier' statement:

    tasks:
    - pexec:
        clients:
          - cd {testdir}/mnt.*
          - while true; do
          -   barrier
          -   dd if=/dev/zero of=./foo count=1024 bs=1024
          - done

    The above writes to the file foo on all clients over and over, but ensures that
    all clients perform each write command in sync.  If one client takes longer to
    write, all the other clients will wait.

    """
    log.info('Executing custom commands...')
    assert isinstance(config, dict), "task pexec got invalid config"

    sudo = False
    if 'sudo' in config:
        sudo = config['sudo']
        del config['sudo']

    testdir = teuthology.get_testdir(ctx)

    remotes = list(_generate_remotes(ctx, config))
    count = len(remotes)
    barrier_queue = _SyncQueue(count)
    barrier = _SyncEvent()

    for remote in remotes:
        _init_barrier(barrier_queue, remote[0])
    with parallel() as p:
        for remote in remotes:
            p.spawn(_exec_host, barrier, barrier_queue, remote[0], sudo, testdir, remote[1])

# Made with Bob
