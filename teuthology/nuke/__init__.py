import logging

log = logging.getLogger(__name__)


# This is being kept because ceph.git/qa/tasks/cephfs/filesystem.py references it.
def clear_firewall(ctx):
    """
    Remove any iptables rules created by teuthology.  These rules are
    identified by containing a comment with 'teuthology' in it.  Non-teuthology
    firewall rules are unaffected.
    """
    log.info("Clearing teuthology firewall rules...")
    ctx.cluster.run(
        args=[
            "sudo", "sh", "-c",
            "iptables-save | grep -v teuthology | iptables-restore"
        ],
    )
    log.info("Cleared teuthology firewall rules.")
