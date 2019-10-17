import contextlib
import logging
import os

from teuthology import misc as teuthology
from teuthology import packaging
from teuthology.orchestra import run

log = logging.getLogger(__name__)


def _get_builder_project(ctx, remote, config):
    return packaging.get_builder_project()(
        config.get('project', 'ceph'),
        config,
        remote=remote,
        ctx=ctx
    )


def _get_local_dir(config, remote):
    """
    Extract local directory name from the task lists.
    Copy files over to the remote site.
    """
    ldir = config.get('local', None)
    if ldir:
        remote.run(args=['sudo', 'mkdir', '-p', ldir])
        for fyle in os.listdir(ldir):
            fname = "%s/%s" % (ldir, fyle)
            teuthology.sudo_write_file(
                remote, fname, open(fname).read(), '644')
    return ldir


def get_flavor(config):
    """
    Determine the flavor to use.
    """
    config = config or dict()
    flavor = config.get('flavor', 'basic')

    if config.get('path'):
        # local dir precludes any other flavors
        flavor = 'local'
    else:
        if config.get('valgrind'):
            flavor = 'notcmalloc'
        else:
            if config.get('coverage'):
                flavor = 'gcov'
    return flavor


@contextlib.contextmanager
def ship_utilities(ctx, config):
    """
    Write a copy of valgrind.supp to each of the remote sites.  Set executables
    used by Ceph in /usr/local/bin.  When finished (upon exit of the teuthology
    run), remove these files.

    :param ctx: Context
    :param config: Configuration
    """
    testdir = teuthology.get_testdir(ctx)
    filenames = []
    if config is None:
        config = dict()
    log.info(config)
    log.info('Shipping valgrind.supp...')
    assert 'suite_path' in ctx.config
    try:
        with open(
            os.path.join(ctx.config['suite_path'], 'valgrind.supp'),
            'rb'
                ) as f:
            fn = os.path.join(testdir, 'valgrind.supp')
            filenames.append(fn)
            for rem in ctx.cluster.remotes.keys():
                teuthology.sudo_write_file(
                    remote=rem,
                    path=fn,
                    data=f,
                    )
                f.seek(0)
    except IOError as e:
        log.info('Cannot ship supression file for valgrind: %s...', e.strerror)

    FILES = ['daemon-helper', 'adjust-ulimits', 'ceph-coverage']
    destdir = '/usr/bin'
    for filename in FILES:
        log.info('Shipping %r...', filename)
        src = os.path.join(os.path.dirname(__file__), filename)
        dst = os.path.join(destdir, filename)
        filenames.append(dst)
        with open(src, 'rb') as f:
            for rem in ctx.cluster.remotes.keys():
                teuthology.sudo_write_file(
                    remote=rem,
                    path=dst,
                    data=f,
                )
                f.seek(0)
                rem.run(
                    args=[
                        'sudo',
                        'chmod',
                        'a=rx',
                        '--',
                        dst,
                    ],
                )

    try:
        yield
    finally:
        if config.get("skipcleanup", False):
            log.info("skipping cleanup of shipped files")
        else:
            log.info('Removing shipped files: %s...', ' '.join(filenames))
            run.wait(
                ctx.cluster.run(
                    args=[
                        'sudo',
                        'rm',
                        '-f',
                        '--',
                    ] + list(filenames),
                    wait=False,
                ),
            )
