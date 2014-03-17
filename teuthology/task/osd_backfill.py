"""
Osd backfill test
"""
import logging
import ceph_manager
import time
from teuthology import misc as teuthology


log = logging.getLogger(__name__)


def rados_start(ctx, remote, cmd):
    """
    Run a remote rados command (currently used to only write data)
    """
    log.info("rados %s" % ' '.join(cmd))
    testdir = teuthology.get_testdir(ctx)
    pre = [
        'adjust-ulimits',
        'ceph-coverage',
        '{tdir}/archive/coverage'.format(tdir=testdir),
        'rados',
        ];
    pre.extend(cmd)
    proc = remote.run(
        args=pre,
        wait=False,
        )
    return proc

def task(ctx, config):
    """
    Test backfill
    """
    if config is None:
        config = {}
    assert isinstance(config, dict), \
        'thrashosds task only accepts a dict for configuration'
    first_mon = teuthology.get_first_mon(ctx, config)
    mon = teuthology.get_single_remote_value(ctx, first_mon)
    
    num_osds = teuthology.num_instances_of_type(ctx.cluster, 'osd')
    log.info('num_osds is %s' % num_osds)
    assert num_osds == 3        

    manager = ceph_manager.CephManager(
        mon,
        ctx=ctx,
        logger=log.getChild('ceph_manager'),
        )

    while len(manager.get_osd_status()['up']) < 3:
        manager.sleep(10)
    manager.raw_cluster_cmd('tell', 'osd.0', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.1', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.2', 'flush_pg_stats')
    manager.wait_for_clean()

    # write some data
    p = rados_start(ctx, mon, ['-p', 'rbd', 'bench', '15', 'write', '-b', '4096',
                          '--no-cleanup'])
    err = p.exitstatus.get();
    log.info('err is %d' % err)

    # mark osd.0 out to trigger a rebalance/backfill
    manager.mark_out_osd(0)

    # also mark it down to it won't be included in pg_temps
    manager.kill_osd(0)
    manager.mark_down_osd(0)

    # wait for everything to peer and be happy...
    manager.raw_cluster_cmd('tell', 'osd.1', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.2', 'flush_pg_stats')
    manager.wait_for_recovery()

    # write some new data
    p = rados_start(ctx, mon, ['-p', 'data', 'bench', '30', 'write', '-b', '4096',
                          '--no-cleanup'])

    time.sleep(15)

    # blackhole + restart osd.1
    # this triggers a divergent backfill target
    manager.blackhole_kill_osd(1)
    time.sleep(2)
    manager.revive_osd(1)

    # wait for our writes to complete + succeed
    err = p.exitstatus.get()
    log.info('err is %d' % err)

    # cluster must recover
    manager.raw_cluster_cmd('tell', 'osd.1', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.2', 'flush_pg_stats')
    manager.wait_for_recovery()

    # re-add osd.0
    manager.revive_osd(0)
    manager.raw_cluster_cmd('tell', 'osd.1', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.2', 'flush_pg_stats')
    manager.wait_for_clean()


