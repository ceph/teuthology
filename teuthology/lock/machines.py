import logging

from teuthology.config import config

from teuthology.lock.lock_server_pool import LockServerMachinePool
from teuthology.lock.sqlite_pool import SqliteMachinePool


log = logging.getLogger(__name__)


def pool():
    if not config.machine_pool or config.machine_pool.startswith('lock_server'):
        log.info("Using lock server machine pool")
        mpool = LockServerMachinePool()
    elif config.machine_pool.startswith('sqlite:'):
        log.info("Using sqlite machine pool @ %s", config.machine_pool)
        mpool = SqliteMachinePool(config.machine_pool)
    return mpool
