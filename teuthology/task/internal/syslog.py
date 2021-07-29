import contextlib
import logging

from io import BytesIO

from teuthology import misc
from teuthology.job_status import set_status
from teuthology.orchestra import run


log = logging.getLogger(__name__)


@contextlib.contextmanager
def syslog(ctx, config):
    """
    start syslog / stop syslog on exit.
    """
    if ctx.archive is None:
        # disable this whole feature if we're not going to archive the data
        # anyway
        yield
        return

    log.info('Starting syslog monitoring...')

    archive_dir = misc.get_archive_dir(ctx)
    log_dir = '{adir}/syslog'.format(adir=archive_dir)
    run.wait(
        ctx.cluster.run(
            args=['mkdir', '-p', '-m0755', '--', log_dir],
            wait=False,
        )
    )

    CONF = '/etc/rsyslog.d/80-cephtest.conf'
    kern_log = '{log_dir}/kern.log'.format(log_dir=log_dir)
    misc_log = '{log_dir}/misc.log'.format(log_dir=log_dir)
    conf_lines = [
        'kern.* -{kern_log};RSYSLOG_FileFormat'.format(kern_log=kern_log),
        '*.*;kern.none -{misc_log};RSYSLOG_FileFormat'.format(
            misc_log=misc_log),
    ]
    conf_fp = BytesIO('\n'.join(conf_lines).encode())
    try:
        for rem in ctx.cluster.remotes.keys():
            log_context = 'system_u:object_r:var_log_t:s0'
            for log_path in (kern_log, misc_log):
                rem.run(args=['install', '-m', '666', '/dev/null', log_path])
                rem.chcon(log_path, log_context)
            misc.sudo_write_file(
                remote=rem,
                path=CONF,
                data=conf_fp,
            )
            conf_fp.seek(0)
        run.wait(
            ctx.cluster.run(
                args=[
                    'sudo',
                    'service',
                    # a mere reload (SIGHUP) doesn't seem to make
                    # rsyslog open the files
                    'rsyslog',
                    'restart',
                ],
                wait=False,
            ),
        )

        yield
    finally:
        log.info('Shutting down syslog monitoring...')

        run.wait(
            ctx.cluster.run(
                args=[
                    'sudo',
                    'rm',
                    '-f',
                    '--',
                    CONF,
                    run.Raw('&&'),
                    'sudo',
                    'service',
                    'rsyslog',
                    'restart',
                ],
                wait=False,
            ),
        )
        # race condition: nothing actually says rsyslog had time to
        # flush the file fully. oh well.

        log.info('Checking logs for errors...')
        exclude_errors = config.get('ignorelist', [])
        log.info('Exclude error list : {0}'.format(exclude_errors))
        for rem in ctx.cluster.remotes.keys():
            log.debug('Checking %s', rem.name)
            args = [
                    'egrep', '--binary-files=text',
                    '\\bBUG\\b|\\bINFO\\b|\\bDEADLOCK\\b|\\bOops\\b|\\bWARNING\\b|\\bKASAN\\b',
                    run.Raw(f'{archive_dir}/syslog/kern.log'),
            ]
            for exclude in exclude_errors:
                args.extend([run.Raw('|'), 'egrep', '-v', exclude])
            args.extend([
                run.Raw('|'), 'head', '-n', '1',
            ])
            stdout = rem.sh(args)
            if stdout != '':
                log.error('Error in syslog on %s: %s', rem.name, stdout)
                set_status(ctx.summary, 'fail')
                if 'failure_reason' not in ctx.summary:
                    ctx.summary['failure_reason'] = \
                        "'{error}' in syslog".format(error=stdout)

        log.info('Compressing syslogs...')
        run.wait(
            ctx.cluster.run(
                args=[
                    'find',
                    '{adir}/syslog'.format(adir=archive_dir),
                    '-name',
                    '*.log',
                    '-print0',
                    run.Raw('|'),
                    'sudo',
                    'xargs',
                    '-0',
                    '--no-run-if-empty',
                    '--',
                    'gzip',
                    '--',
                ],
                wait=False,
            )
        )

        log.info('Gathering journactl -b0...')
        run.wait(
            ctx.cluster.run(
                args=[
                    'sudo', 'journalctl', '-b0',
                    run.Raw('|'),
                    'gzip', '-9',
                    run.Raw('>'),
                    f'{archive_dir}/syslog/journalctl-b0.gz',
                ],
                wait=False,
            )
        )
