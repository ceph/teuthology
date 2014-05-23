"""
Clock synchronizer
"""
import logging
import contextlib

from ..orchestra import run

log = logging.getLogger(__name__)

@contextlib.contextmanager
def task(ctx, config):
    """
    Sync or skew clock

    This will initially sync the clocks.  Eventually it should let us also
    skew by some number of seconds.

    example:

    tasks:
    - clock:
    - ceph:
    - interactive:

    to sync.

    :param ctx: Context
    :param config: Configuration
    """

    log.info('Syncing clocks and checking initial clock skew...')
    for rem in ctx.cluster.remotes.iterkeys():
        rem.run(
            args=[
                'sudo',
                'service', 'ntp', 'stop',
                run.Raw(';'),
                'sudo',
                'ntpdate',
#                'clock1.dreamhost.com',
#                'clock2.dreamhost.com',
#                'clock3.dreamhost.com',
#                'time.apple.com',
                '0.debian.pool.ntp.org',
                '1.debian.pool.ntp.org',
                '2.debian.pool.ntp.org',
                '3.debian.pool.ntp.org',
                run.Raw(';'),
                'sudo',
                'service', 'ntp', 'start',
                run.Raw(';'),
                'PATH=/usr/bin:/usr/sbin',
                'ntpdc', '-p',
                ],
        )

    try:
        yield

    finally:
        log.info('Checking final clock skew...')
        for rem in ctx.cluster.remotes.iterkeys():
            rem.run(
                args=[
                    'PATH=/usr/bin:/usr/sbin',
                    'ntpdc', '-p',
                    ],
                )


@contextlib.contextmanager
def check(ctx, config):
    """
    Run ntpdc at the start and the end of the task.

    :param ctx: Context
    :param config: Configuration
    """
    log.info('Checking initial clock skew...')
    for rem in ctx.cluster.remotes.iterkeys():
        rem.run(
            args=[
                'PATH=/usr/bin:/usr/sbin',
                'ntpdc', '-p',
                ],
            )

    try:
        yield

    finally:
        log.info('Checking final clock skew...')
        for rem in ctx.cluster.remotes.iterkeys():
            rem.run(
                args=[
                    'PATH=/usr/bin:/usr/sbin',
                    'ntpdc', '-p',
                    ],
                )
