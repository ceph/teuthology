import logging
import time

import teuthology
from teuthology.salt import Salt

log = logging.getLogger(__name__)

def task(ctx, config):
    """
    Do the same thing as ansible.cephlab, but in a minimalistic manner (just
    for OpenStack and, for the time being, just for openSUSE)
    """
    log.info("Starting ceph_cm_salt task")
    salt = Salt(ctx, config)
    salt.generate_minion_keys()
    salt.preseed_minions()
    salt.set_minion_master()
    salt.start_minions(ctx)
    log.info("Going to sleep")
    time.sleep(10000000)
