
import logging

from teuthology.config import config
from teuthology.machines.base import MachinePool
from teuthology.machines.lock_server_pool import LockServerMachinePool
from teuthology.machines.sqlite_pool import SqliteMachinePool


log = logging.getLogger(__name__)


def from_config() -> MachinePool:
    if not config.machine_pool or config.machine_pool.startswith(
        'lock_server'
    ):
        mpool = LockServerMachinePool()
    elif config.machine_pool.startswith('sqlite:'):
        mpool = SqliteMachinePool()
    log.info("Using machine pool: %s", mpool.description())
    return mpool


def auto_pool(ctx=None, pool: MachinePool | None = None) -> MachinePool:
    if pool is not None:
        return pool
    # TODO: cached pool on ctx if ctx is given
    return from_config()
