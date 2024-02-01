import contextlib
import logging

import teuthology.lock.ops
import teuthology.lock.query
import teuthology.lock.util

log = logging.getLogger(__name__)


@contextlib.contextmanager
def lock_machines(ctx, config):
    """
    Lock machines.  Called when the teuthology run finds and locks
    new machines.  This is not called if the one has teuthology-locked
    machines and placed those keys in the Targets section of a yaml file.
    """
    assert isinstance(config[0], int), 'config[0] must be an integer'
    machine_type = config[1]
    total_requested = config[0]
    # We want to make sure there are always this many machines available
    teuthology.lock.ops.block_and_lock_machines(ctx, total_requested, machine_type)
    try:
        yield
    finally:
        if ctx.config.get("unlock_on_failure", True):
            log.info('Unlocking machines...')
            for machine in ctx.config['targets'].keys():
                teuthology.lock.ops.unlock_one(machine, ctx.owner, ctx.archive)
