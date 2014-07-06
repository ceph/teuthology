"""
Lost_unfound
"""
import logging
import ceph_manager
from teuthology import misc as teuthology
from teuthology.task_util.rados import rados

log = logging.getLogger(__name__)

def task(ctx, config):
    """
    Test handling of lost objects on an ec pool.

    A pretty rigid cluster is brought up andtested by this task
    """
    if config is None:
        config = {}
    assert isinstance(config, dict), \
        'lost_unfound task only accepts a dict for configuration'
    first_mon = teuthology.get_first_mon(ctx, config)
    (mon,) = ctx.cluster.only(first_mon).remotes.iterkeys()

    manager = ceph_manager.CephManager(
        mon,
        ctx=ctx,
        logger=log.getChild('ceph_manager'),
        )

    manager.raw_cluster_cmd('tell', 'osd.0', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.1', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.2', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.3', 'flush_pg_stats')
    manager.wait_for_clean()


    manager.create_erasure_code_profile(
        profile_name='m2k2',
        profile={'m': 2, 'k': 2}
        )
    pool = manager.create_pool_with_unique_name(
        erasure_code_profile_name='m2k2'
        )

    # something that is always there
    dummyfile = '/etc/fstab'

    # kludge to make sure they get a map
    rados(ctx, mon, ['-p', pool, 'put', 'dummy', dummyfile])

    manager.raw_cluster_cmd('tell', 'osd.0', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.1', 'flush_pg_stats')
    manager.wait_for_recovery()

    # create old objects
    for f in range(1, 10):
        rados(ctx, mon, ['-p', pool, 'put', 'existing_%d' % f, dummyfile])
        rados(ctx, mon, ['-p', pool, 'put', 'existed_%d' % f, dummyfile])
        rados(ctx, mon, ['-p', pool, 'rm', 'existed_%d' % f])

    # delay recovery, and make the pg log very long (to prevent backfill)
    manager.raw_cluster_cmd(
            'tell', 'osd.1',
            'injectargs',
            '--osd-recovery-delay-start 1000 --osd-min-pg-log-entries 100000000'
            )

    manager.kill_osd(0)
    manager.mark_down_osd(0)
    manager.kill_osd(3)
    manager.mark_down_osd(3)
    
    for f in range(1, 10):
        rados(ctx, mon, ['-p', pool, 'put', 'new_%d' % f, dummyfile])
        rados(ctx, mon, ['-p', pool, 'put', 'existed_%d' % f, dummyfile])
        rados(ctx, mon, ['-p', pool, 'put', 'existing_%d' % f, dummyfile])

    # take out osd.1 and a necessary shard of those objects.
    manager.kill_osd(1)
    manager.mark_down_osd(1)
    manager.raw_cluster_cmd('osd', 'lost', '1', '--yes-i-really-mean-it')
    manager.revive_osd(0)
    manager.wait_till_osd_is_up(0)
    manager.revive_osd(3)
    manager.wait_till_osd_is_up(3)

    manager.raw_cluster_cmd('tell', 'osd.0', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.2', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.3', 'flush_pg_stats')
    manager.wait_till_active()
    manager.raw_cluster_cmd('tell', 'osd.0', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.2', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.3', 'flush_pg_stats')

    # verify that there are unfound objects
    unfound = manager.get_num_unfound_objects()
    log.info("there are %d unfound objects" % unfound)
    assert unfound

    # mark stuff lost
    pgs = manager.get_pg_stats()
    for pg in pgs:
        if pg['stat_sum']['num_objects_unfound'] > 0:
            # verify that i can list them direct from the osd
            log.info('listing missing/lost in %s state %s', pg['pgid'],
                     pg['state']);
            m = manager.list_pg_missing(pg['pgid'])
            log.info('%s' % m)
            assert m['num_unfound'] == pg['stat_sum']['num_objects_unfound']

            log.info("reverting unfound in %s", pg['pgid'])
            manager.raw_cluster_cmd('pg', pg['pgid'],
                                    'mark_unfound_lost', 'delete')
        else:
            log.info("no unfound in %s", pg['pgid'])

    manager.raw_cluster_cmd('tell', 'osd.0', 'debug', 'kick_recovery_wq', '5')
    manager.raw_cluster_cmd('tell', 'osd.2', 'debug', 'kick_recovery_wq', '5')
    manager.raw_cluster_cmd('tell', 'osd.3', 'debug', 'kick_recovery_wq', '5')
    manager.raw_cluster_cmd('tell', 'osd.0', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.2', 'flush_pg_stats')
    manager.raw_cluster_cmd('tell', 'osd.3', 'flush_pg_stats')
    manager.wait_for_recovery()

    # verify result
    for f in range(1, 10):
        err = rados(ctx, mon, ['-p', pool, 'get', 'new_%d' % f, '-'])
        assert err
        err = rados(ctx, mon, ['-p', pool, 'get', 'existed_%d' % f, '-'])
        assert err
        err = rados(ctx, mon, ['-p', pool, 'get', 'existing_%d' % f, '-'])
        assert err

    # see if osd.1 can cope
    manager.revive_osd(1)
    manager.wait_till_osd_is_up(1)
    manager.wait_for_clean()
