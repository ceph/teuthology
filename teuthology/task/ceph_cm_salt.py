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
    log.info("ceph_cm_salt: begin")
    salt = Salt(ctx, config)
    salt.init_minions()
    salt.start_minions()
    salt.ping_minions()
    log.info("ceph_cm_salt: end")
    #log.info("Going to sleep at the end of ceph_cm_salt task")
    #time.sleep(10000000)
