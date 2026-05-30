"""
Localdir
"""
import contextlib
import logging
import os

from teuthology import misc

log = logging.getLogger(__name__)


@contextlib.contextmanager
def task(ctx, config):
    """
    Create a mount dir 'client' that is just the local disk:

    Example that "mounts" all clients:

        tasks:
        - localdir:
        - interactive:

    Example for a specific client:

        tasks:
        - localdir: [client.2]
        - interactive:

    :param ctx: Context
    :param config: Configuration
    """
    log.info('Creating local mnt dirs...')

    testdir = misc.get_testdir(ctx)

    if config is None:
        config = list('client.{id}'.format(id=id_)
                      for id_ in misc.all_roles_of_type(ctx.cluster,
                                                              'client'))

    clients = list(misc.get_clients(ctx=ctx, roles=config))
    for id_, remote in clients:
        mnt = os.path.join(testdir, 'mnt.{id}'.format(id=id_))
        log.info('Creating dir {remote} {mnt}...'.format(
                remote=remote, mnt=mnt))
        remote.run(
            args=[
                'mkdir',
                '--',
                mnt,
                ],
            )

    try:
        yield

    finally:
        log.info('Removing local mnt dirs...')
        for id_, remote in clients:
            mnt = os.path.join(testdir, 'mnt.{id}'.format(id=id_))
            remote.run(
                args=[
                    'rm',
                    '-rf',
                    '--',
                    mnt,
                    ],
                )
