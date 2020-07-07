import contextlib
import logging

from teuthology.task.internal.lock_machines import unlock_machines

log = logging.getLogger(__name__)


@contextlib.contextmanager
def unlock_targets(ctx, config):
    """
    Unlock target machines. Called when the job has target machines
    specified in the job config. It unlocks the targets at the end
    of the teuthology run. This is not called if teuthology run locks
    machines.
    """
    try:
        yield
    finally:
        unlock_machines(ctx)
