"""
Handle parallel execution on remote hosts
"""
import asyncio
import logging

from teuthology import misc as teuthology
from teuthology.orchestra.run import PIPE

log = logging.getLogger(__name__)

def _exec_host(remote, sudo, testdir, ls):
    """Execute command remotely"""
    log.info('Running commands on host %s', remote.name)
    args = [
        'TESTDIR={tdir}'.format(tdir=testdir),
        'bash',
        '-s'
        ]
    if sudo:
        args.insert(0, 'sudo')
    
    r = remote.run( args=args, stdin=PIPE, wait=False)
    r.stdin.writelines(['set -e\n'])
    r.stdin.flush()
    for l in ls:
        l.replace('$TESTDIR', testdir)
        r.stdin.writelines([l, '\n'])
        r.stdin.flush()
    r.stdin.writelines(['\n'])
    r.stdin.flush()
    r.stdin.close()
    return r.wait()

def _generate_remotes(ctx, config):
    """Return remote roles and the type of role specified in config"""
    if 'all' in config and len(config) == 1:
        ls = config['all']
        for remote in ctx.cluster.remotes.keys():
            yield (remote, ls)
    elif 'clients' in config:
        ls = config['clients']
        for role in teuthology.all_roles_of_type(ctx.cluster, 'client'):
            (remote,) = ctx.cluster.only('client.{r}'.format(r=role)).remotes.keys()
            yield (remote, ls)
        del config['clients']
        for role, ls in config.items():
            (remote,) = ctx.cluster.only(role).remotes.keys()
            yield (remote, ls)
    else:
        for role, ls in config.items():
            (remote,) = ctx.cluster.only(role).remotes.keys()
            yield (remote, ls)

async def task(ctx, config):
    """
    Execute commands on multiple hosts in parallel

        tasks:
        - ceph:
        - ceph-fuse: [client.0, client.1]
        - pexec:
            client.0:
              - while true; do echo foo >> bar; done
            client.1:
              - sleep 1
              - tail -f bar
        - interactive:

    Execute commands on all hosts in the cluster in parallel.  This
    is useful if there are many hosts and you want to run the same
    command on all:

        tasks:
        - pexec:
            all:
              - grep FAIL /var/log/ceph/*

    Or if you want to run in parallel on all clients:

        tasks:
        - pexec:
            clients:
              - dd if=/dev/zero of={testdir}/mnt.* count=1024 bs=1024
    """
    log.info('Executing custom commands...')
    assert isinstance(config, dict), "task pexec got invalid config"

    sudo = False
    if 'sudo' in config:
        sudo = config['sudo']
        del config['sudo']

    testdir = teuthology.get_testdir(ctx)

    remotes = list(_generate_remotes(ctx, config))
    tasks = set()
    for remote in remotes:
        task = _exec_host(remote[0], sudo, testdir, remote[1])
        # FIXME
        # task = asyncio.create_task(
        #     _exec_host(remote[0], sudo, testdir, remote[1])
        # )
        tasks.add(task)
    await asyncio.gather(*tasks)
