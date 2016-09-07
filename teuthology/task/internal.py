"""
Internal tasks are tasks that are started from the teuthology infrastructure.
Note that there is no corresponding task defined for this module.  All of
the calls are made from other modules, most notably teuthology/run.py
"""
from cStringIO import StringIO
import contextlib
import logging
import os
import time
import yaml
import subprocess

from teuthology import lockstatus
from teuthology import lock
from teuthology import misc
from teuthology import provision
from teuthology.packaging import GitbuilderProject
from teuthology.exceptions import VersionNotFoundError
from teuthology.job_status import get_status, set_status
from teuthology.config import config as teuth_config
from teuthology.parallel import parallel
from ..orchestra import cluster, remote, run
from .. import report
from . import ansible

log = logging.getLogger(__name__)


@contextlib.contextmanager
def base(ctx, config):
    """
    Create the test directory that we will be using on the remote system
    """
    log.info('Creating test directory...')
    testdir = misc.get_testdir(ctx)
    run.wait(
        ctx.cluster.run(
            args=['mkdir', '-p', '-m0755', '--', testdir],
            wait=False,
        )
    )
    try:
        yield
    finally:
        log.info('Tidying up after the test...')
        # if this fails, one of the earlier cleanups is flawed; don't
        # just cram an rm -rf here
        run.wait(
            ctx.cluster.run(
                args=['find', testdir, '-ls',
                      run.Raw(';'),
                      'rmdir', '--', testdir],
                wait=False,
            ),
        )


@contextlib.contextmanager
def lock_machines(ctx, config):
    """
    Lock machines.  Called when the teuthology run finds and locks
    new machines.  This is not called if the one has teuthology-locked
    machines and placed those keys in the Targets section of a yaml file.
    """
    # It's OK for os_type and os_version to be None here.  If we're trying
    # to lock a bare metal machine, we'll take whatever is available.  If
    # we want a vps, defaults will be provided by misc.get_distro and
    # misc.get_distro_version in provision.create_if_vm
    os_type = ctx.config.get("os_type")
    os_version = ctx.config.get("os_version")
    arch = ctx.config.get('arch')
    log.info('Locking machines...')
    assert isinstance(config[0], int), 'config[0] must be an integer'
    machine_type = config[1]
    total_requested = config[0]
    # We want to make sure there are always this many machines available
    reserved = teuth_config.reserve_machines
    assert isinstance(reserved, int), 'reserve_machines must be integer'
    assert (reserved >= 0), 'reserve_machines should >= 0'

    # change the status during the locking process
    report.try_push_job_info(ctx.config, dict(status='waiting'))

    all_locked = dict()
    requested = total_requested
    while True:
        # get a candidate list of machines
        machines = lock.list_locks(machine_type=machine_type, up=True,
                                   locked=False, count=requested + reserved)
        if machines is None:
            if ctx.block:
                log.error('Error listing machines, trying again')
                time.sleep(20)
                continue
            else:
                raise RuntimeError('Error listing machines')

        # make sure there are machines for non-automated jobs to run
        if len(machines) < reserved + requested and ctx.owner.startswith('scheduled'):
            if ctx.block:
                log.info(
                    'waiting for more %s machines to be free (need %s + %s, have %s)...',
                    machine_type,
                    reserved,
                    requested,
                    len(machines),
                )
                time.sleep(10)
                continue
            else:
                assert 0, ('not enough machines free; need %s + %s, have %s' %
                           (reserved, requested, len(machines)))

        try:
            newly_locked = lock.lock_many(ctx, requested, machine_type,
                                          ctx.owner, ctx.archive, os_type,
                                          os_version, arch)
        except Exception:
            # Lock failures should map to the 'dead' status instead of 'fail'
            set_status(ctx.summary, 'dead')
            raise
        all_locked.update(newly_locked)
        log.info(
            '{newly_locked} {mtype} machines locked this try, '
            '{total_locked}/{total_requested} locked so far'.format(
                newly_locked=len(newly_locked),
                mtype=machine_type,
                total_locked=len(all_locked),
                total_requested=total_requested,
            )
        )
        if len(all_locked) == total_requested:
            vmlist = []
            for lmach in all_locked:
                if misc.is_vm(lmach):
                    vmlist.append(lmach)
            if vmlist:
                log.info('Waiting for virtual machines to come up')
                keys_dict = dict()
                loopcount = 0
                while len(keys_dict) != len(vmlist):
                    loopcount += 1
                    time.sleep(10)
                    keys_dict = misc.ssh_keyscan(vmlist)
                    log.info('virtual machine is still unavailable')
                    if loopcount == 40:
                        loopcount = 0
                        log.info('virtual machine(s) still not up, ' +
                                 'recreating unresponsive ones.')
                        for guest in vmlist:
                            if guest not in keys_dict.keys():
                                log.info('recreating: ' + guest)
                                full_name = misc.canonicalize_hostname(guest)
                                provision.destroy_if_vm(ctx, full_name)
                                provision.create_if_vm(ctx, full_name)
                if lock.do_update_keys(keys_dict):
                    log.info("Error in virtual machine keys")
                newscandict = {}
                for dkey in all_locked.iterkeys():
                    stats = lockstatus.get_status(dkey)
                    newscandict[dkey] = stats['ssh_pub_key']
                ctx.config['targets'] = newscandict
            else:
                ctx.config['targets'] = all_locked
            locked_targets = yaml.safe_dump(
                ctx.config['targets'],
                default_flow_style=False
            ).splitlines()
            log.info('\n  '.join(['Locked targets:', ] + locked_targets))
            # successfully locked machines, change status back to running
            report.try_push_job_info(ctx.config, dict(status='running'))
            break
        elif not ctx.block:
            assert 0, 'not enough machines are available'
        else:
            requested = requested - len(newly_locked)
            assert requested > 0, "lock_machines: requested counter went" \
                                  "negative, this shouldn't happen"

        log.info(
            "{total} machines locked ({new} new); need {more} more".format(
                total=len(all_locked), new=len(newly_locked), more=requested)
        )
        log.warn('Could not lock enough machines, waiting...')
        time.sleep(10)
    try:
        yield
    finally:
        # If both unlock_on_failure and nuke-on-error are set, don't unlock now
        # because we're just going to nuke (and unlock) later.
        unlock_on_failure = (
            ctx.config.get('unlock_on_failure', False)
            and not ctx.config.get('nuke-on-error', False)
        )
        if get_status(ctx.summary) == 'pass' or unlock_on_failure:
            log.info('Unlocking machines...')
            for machine in ctx.config['targets'].iterkeys():
                lock.unlock_one(ctx, machine, ctx.owner, ctx.archive)


def save_config(ctx, config):
    """
    Store the config in a yaml file
    """
    log.info('Saving configuration')
    if ctx.archive is not None:
        with file(os.path.join(ctx.archive, 'config.yaml'), 'w') as f:
            yaml.safe_dump(ctx.config, f, default_flow_style=False)


def check_lock(ctx, config, check_up=True):
    """
    Check lock status of remote machines.
    """
    if not teuth_config.lock_server or ctx.config.get('check-locks') is False:
        log.info('Lock checking disabled.')
        return
    log.info('Checking locks...')
    for machine in ctx.config['targets'].iterkeys():
        status = lockstatus.get_status(machine)
        log.debug('machine status is %s', repr(status))
        assert status is not None, \
            'could not read lock status for {name}'.format(name=machine)
        if check_up:
            assert status['up'], 'machine {name} is marked down'.format(
                name=machine
            )
        assert status['locked'], \
            'machine {name} is not locked'.format(name=machine)
        assert status['locked_by'] == ctx.owner, \
            'machine {name} is locked by {user}, not {owner}'.format(
                name=machine,
                user=status['locked_by'],
                owner=ctx.owner,
            )


def check_packages(ctx, config):
    """
    Checks gitbuilder to determine if there are missing packages for this job.

    If there are missing packages, fail the job.
    """
    for task in ctx.config['tasks']:
        if task.keys()[0] == 'buildpackages':
            log.info("Checking packages skipped because "
                     "the task buildpackages was found.")
            return

    log.info("Checking packages...")
    os_type = ctx.config.get("os_type")
    sha1 = ctx.config.get("sha1")
    # We can only do this check if there are a defined sha1 and os_type
    # in the job config.
    if os_type and sha1:
        package = GitbuilderProject("ceph", ctx.config)
        template = "Checking packages for os_type,'{os}' flavor '{flav}' and" \
            " ceph hash '{ver}'"
        log.info(
            template.format(
                os=package.os_type,
                flav=package.flavor,
                ver=package.sha1,
            )
        )
        if package.version:
            log.info("Found packages for ceph version {ver}".format(
                ver=package.version
            ))
        else:
            msg = "Packages for distro '{d}' and ceph hash '{ver}' not found"
            msg = msg.format(
                d=package.distro,
                ver=package.sha1,
            )
            log.error(msg)
            # set the failure message and update paddles with the status
            ctx.summary["failure_reason"] = msg
            set_status(ctx.summary, "dead")
            report.try_push_job_info(ctx.config, dict(status='dead'))
            raise VersionNotFoundError(package.base_url)
    else:
        log.info(
            "Checking packages skipped, missing os_type '{os}' or ceph hash '{ver}'".format(
                os=os_type,
                ver=sha1,
            )
        )


@contextlib.contextmanager
def timer(ctx, config):
    """
    Start the timer used by teuthology
    """
    log.info('Starting timer...')
    start = time.time()
    try:
        yield
    finally:
        duration = time.time() - start
        log.info('Duration was %f seconds', duration)
        ctx.summary['duration'] = duration


def add_remotes(ctx, config):
    """
    Create a ctx.cluster object populated with remotes mapped to roles
    """
    remotes = []
    machs = []
    for name in ctx.config['targets'].iterkeys():
        machs.append(name)
    for t, key in ctx.config['targets'].iteritems():
        t = misc.canonicalize_hostname(t)
        try:
            if ctx.config['sshkeys'] == 'ignore':
                key = None
        except (AttributeError, KeyError):
            pass
        rem = remote.Remote(name=t, host_key=key, keep_alive=True)
        remotes.append(rem)
    ctx.cluster = cluster.Cluster()
    if 'roles' in ctx.config:
        for rem, roles in zip(remotes, ctx.config['roles']):
            assert all(isinstance(role, str) for role in roles), \
                "Roles in config must be strings: %r" % roles
            ctx.cluster.add(rem, roles)
            log.info('roles: %s - %s' % (rem, roles))
    else:
        for rem in remotes:
            ctx.cluster.add(rem, rem.name)


def connect(ctx, config):
    """
    Connect to all remotes in ctx.cluster
    """
    log.info('Opening connections...')
    for rem in ctx.cluster.remotes.iterkeys():
        log.debug('connecting to %s', rem.name)
        rem.connect()


def push_inventory(ctx, config):
    if not teuth_config.lock_server:
        return

    def push():
        for rem in ctx.cluster.remotes.keys():
            info = rem.inventory_info
            lock.update_inventory(info)
    try:
        push()
    except Exception:
        log.exception("Error pushing inventory")

BUILDPACKAGES_FIRST = 0
BUILDPACKAGES_OK = 1
BUILDPACKAGES_REMOVED = 2
BUILDPACKAGES_NOTHING = 3

def buildpackages_prep(ctx, config):
    """
    Make sure the 'buildpackages' task happens before
    the 'install' task.

    Return:

    BUILDPACKAGES_NOTHING if there is no buildpackages task
    BUILDPACKAGES_REMOVED if there is a buildpackages task but no install task
    BUILDPACKAGES_FIRST if a buildpackages task was moved at the beginning
    BUILDPACKAGES_OK if a buildpackages task already at the beginning
    """
    index = 0
    install_index = None
    buildpackages_index = None
    buildpackages_prep_index = None
    for task in ctx.config['tasks']:
        if task.keys()[0] == 'install':
            install_index = index
        if task.keys()[0] == 'buildpackages':
            buildpackages_index = index
        if task.keys()[0] == 'internal.buildpackages_prep':
            buildpackages_prep_index = index
        index += 1
    if (buildpackages_index is not None and
        install_index is not None):
        if buildpackages_index > buildpackages_prep_index + 1:
            log.info('buildpackages moved to be the first task')
            buildpackages = ctx.config['tasks'].pop(buildpackages_index)
            ctx.config['tasks'].insert(buildpackages_prep_index + 1,
                                       buildpackages)
            return BUILDPACKAGES_FIRST
        else:
            log.info('buildpackages is already the first task')
            return BUILDPACKAGES_OK
    elif buildpackages_index is not None and install_index is None:
        ctx.config['tasks'].pop(buildpackages_index)
        all_tasks = [x.keys()[0] for x in ctx.config['tasks']]
        log.info('buildpackages removed because no install task found in ' +
                 str(all_tasks))
        return BUILDPACKAGES_REMOVED
    elif buildpackages_index is None:
        log.info('no buildpackages task found')
        return BUILDPACKAGES_NOTHING


def serialize_remote_roles(ctx, config):
    """
    Provides an explicit mapping for which remotes have been assigned what roles
    So that other software can be loosely coupled to teuthology
    """
    if ctx.archive is not None:
        with file(os.path.join(ctx.archive, 'info.yaml'), 'r+') as info_file:
            info_yaml = yaml.safe_load(info_file)
            info_file.seek(0)
            info_yaml['cluster'] = dict([(rem.name, {'roles': roles}) for rem, roles in ctx.cluster.remotes.iteritems()])
            yaml.safe_dump(info_yaml, info_file, default_flow_style=False)


def check_ceph_data(ctx, config):
    """
    Check for old /var/lib/ceph directories and detect staleness.
    """
    log.info('Checking for old /var/lib/ceph...')
    processes = ctx.cluster.run(
        args=['test', '!', '-e', '/var/lib/ceph'],
        wait=False,
    )
    failed = False
    for proc in processes:
        try:
            proc.wait()
        except run.CommandFailedError:
            log.error('Host %s has stale /var/lib/ceph, check lock and nuke/cleanup.', proc.remote.shortname)
            failed = True
    if failed:
        raise RuntimeError('Stale /var/lib/ceph detected, aborting.')


def check_conflict(ctx, config):
    """
    Note directory use conflicts and stale directories.
    """
    log.info('Checking for old test directory...')
    testdir = misc.get_testdir(ctx)
    processes = ctx.cluster.run(
        args=['test', '!', '-e', testdir],
        wait=False,
    )
    failed = False
    for proc in processes:
        try:
            proc.wait()
        except run.CommandFailedError:
            log.error('Host %s has stale test directory %s, check lock and cleanup.', proc.remote.shortname, testdir)
            failed = True
    if failed:
        raise RuntimeError('Stale jobs detected, aborting.')


def fetch_binaries_for_coredumps(path, remote):
    """
    Pul ELFs (debug and stripped) for each coredump found
    """
    # Check for Coredumps:
    coredump_path = os.path.join(path, 'coredump')
    if os.path.isdir(coredump_path):
        log.info('Transferring binaries for coredumps...')
        for dump in os.listdir(coredump_path):
            # Pull program from core file
            dump_path = os.path.join(coredump_path, dump)
            dump_info = subprocess.Popen(['file', dump_path],
                                         stdout=subprocess.PIPE)
            dump_out = dump_info.communicate()

            # Parse file output to get program, Example output:
            # 1422917770.7450.core: ELF 64-bit LSB core file x86-64, version 1 (SYSV), SVR4-style, \
            # from 'radosgw --rgw-socket-path /home/ubuntu/cephtest/apache/tmp.client.0/fastcgi_soc'
            dump_program = dump_out.split("from '")[1].split(' ')[0]

            # Find path on remote server:
            r = remote.run(args=['which', dump_program], stdout=StringIO())
            remote_path = r.stdout.getvalue()

            # Pull remote program into coredump folder:
            remote._sftp_get_file(remote_path, os.path.join(coredump_path,
                                                            dump_program))

            # Pull Debug symbols:
            debug_path = os.path.join('/usr/lib/debug', remote_path)

            # RPM distro's append their non-stripped ELF's with .debug
            # When deb based distro's do not.
            if remote.system_type == 'rpm':
                debug_path = '{debug_path}.debug'.format(debug_path=debug_path)

            remote.get_file(debug_path, coredump_path)


@contextlib.contextmanager
def archive(ctx, config):
    """
    Handle the creation and deletion of the archive directory.
    """
    log.info('Creating archive directory...')
    archive_dir = misc.get_archive_dir(ctx)
    run.wait(
        ctx.cluster.run(
            args=['install', '-d', '-m0755', '--', archive_dir],
            wait=False,
        )
    )

    try:
        yield
    except Exception:
        # we need to know this below
        set_status(ctx.summary, 'fail')
        raise
    finally:
        passed = get_status(ctx.summary) == 'pass'
        if ctx.archive is not None and \
                not (ctx.config.get('archive-on-error') and passed):
            log.info('Transferring archived files...')
            logdir = os.path.join(ctx.archive, 'remote')
            if (not os.path.exists(logdir)):
                os.mkdir(logdir)
            for rem in ctx.cluster.remotes.iterkeys():
                path = os.path.join(logdir, rem.shortname)
                misc.pull_directory(rem, archive_dir, path)
                # Check for coredumps and pull binaries
                fetch_binaries_for_coredumps(path, rem)

        log.info('Removing archive directory...')
        run.wait(
            ctx.cluster.run(
                args=['rm', '-rf', '--', archive_dir],
                wait=False,
            ),
        )


@contextlib.contextmanager
def sudo(ctx, config):
    """
    Enable use of sudo
    """
    log.info('Configuring sudo...')
    sudoers_file = '/etc/sudoers'
    backup_ext = '.orig.teuthology'
    tty_expr = r's/^\([^#]*\) \(requiretty\)/\1 !\2/g'
    pw_expr = r's/^\([^#]*\) !\(visiblepw\)/\1 \2/g'

    run.wait(
        ctx.cluster.run(
            args="sudo sed -i{ext} -e '{tty}' -e '{pw}' {path}".format(
                ext=backup_ext, tty=tty_expr, pw=pw_expr,
                path=sudoers_file
            ),
            wait=False,
        )
    )
    try:
        yield
    finally:
        log.info('Restoring {0}...'.format(sudoers_file))
        ctx.cluster.run(
            args="sudo mv -f {path}{ext} {path}".format(
                path=sudoers_file, ext=backup_ext
            )
        )


@contextlib.contextmanager
def coredump(ctx, config):
    """
    Stash a coredump of this system if an error occurs.
    """
    log.info('Enabling coredump saving...')
    archive_dir = misc.get_archive_dir(ctx)
    run.wait(
        ctx.cluster.run(
            args=[
                'install', '-d', '-m0755', '--',
                '{adir}/coredump'.format(adir=archive_dir),
                run.Raw('&&'),
                'sudo', 'sysctl', '-w', 'kernel.core_pattern={adir}/coredump/%t.%p.core'.format(adir=archive_dir),
            ],
            wait=False,
        )
    )

    try:
        yield
    finally:
        run.wait(
            ctx.cluster.run(
                args=[
                    'sudo', 'sysctl', '-w', 'kernel.core_pattern=core',
                    run.Raw('&&'),
                    # don't litter the archive dir if there were no cores dumped
                    'rmdir',
                    '--ignore-fail-on-non-empty',
                    '--',
                    '{adir}/coredump'.format(adir=archive_dir),
                ],
                wait=False,
            )
        )

        # set status = 'fail' if the dir is still there = coredumps were
        # seen
        for rem in ctx.cluster.remotes.iterkeys():
            r = rem.run(
                args=[
                    'if', 'test', '!', '-e', '{adir}/coredump'.format(adir=archive_dir), run.Raw(';'), 'then',
                    'echo', 'OK', run.Raw(';'),
                    'fi',
                ],
                stdout=StringIO(),
            )
            if r.stdout.getvalue() != 'OK\n':
                log.warning('Found coredumps on %s, flagging run as failed', rem)
                set_status(ctx.summary, 'fail')
                if 'failure_reason' not in ctx.summary:
                    ctx.summary['failure_reason'] = \
                        'Found coredumps on {rem}'.format(rem=rem)


@contextlib.contextmanager
def archive_upload(ctx, config):
    """
    Upload the archive directory to a designated location
    """
    try:
        yield
    finally:
        upload = ctx.config.get('archive_upload')
        archive_path = ctx.config.get('archive_path')
        if upload and archive_path:
            log.info('Uploading archives ...')
            upload_key = ctx.config.get('archive_upload_key')
            if upload_key:
                ssh = "RSYNC_RSH='ssh -i " + upload_key + "'"
            else:
                ssh = ''
            split_path = archive_path.split('/')
            split_path.insert(-2, '.')
            misc.sh(ssh + " rsync -avz --relative /" +
                    os.path.join(*split_path) + " " +
                    upload)
        else:
            log.info('Not uploading archives.')

@contextlib.contextmanager
def syslog(ctx, config):
    """
    start syslog / stop syslog on exit.
    """
    if ctx.archive is None:
        # disable this whole feature if we're not going to archive the data anyway
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
    conf_fp = StringIO('\n'.join(conf_lines))
    try:
        for rem in ctx.cluster.remotes.iterkeys():
            log_context = 'system_u:object_r:var_log_t:s0'
            for log_path in (kern_log, misc_log):
                rem.run(args='touch %s' % log_path)
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
        for rem in ctx.cluster.remotes.iterkeys():
            log.debug('Checking %s', rem.name)
            r = rem.run(
                args=[
                    'egrep', '--binary-files=text',
                    '\\bBUG\\b|\\bINFO\\b|\\bDEADLOCK\\b',
                    run.Raw('{adir}/syslog/*.log'.format(adir=archive_dir)),
                    run.Raw('|'),
                    'grep', '-v', 'task .* blocked for more than .* seconds',
                    run.Raw('|'),
                    'grep', '-v', 'lockdep is turned off',
                    run.Raw('|'),
                    'grep', '-v', 'trying to register non-static key',
                    run.Raw('|'),
                    'grep', '-v', 'DEBUG: fsize',  # xfs_fsr
                    run.Raw('|'),
                    'grep', '-v', 'INFO: possible circular locking dependency detected', # sadly, there is an xfs vs vfs splice locking issue
                    run.Raw('|'),
                    'grep', '-v', 'CRON',  # ignore cron noise
                    run.Raw('|'),
                    'grep', '-v', 'BUG: bad unlock balance detected',  # #6097
                    run.Raw('|'),
                    'grep', '-v', 'inconsistent lock state',  # FIXME see #2523
                    run.Raw('|'),
                    'grep', '-v', '*** DEADLOCK ***',  # part of lockdep output
                    run.Raw('|'),
                    'grep', '-v', 'INFO: possible irq lock inversion dependency detected',  # FIXME see #2590 and #147
                    run.Raw('|'),
                    'grep', '-v', 'INFO: NMI handler (perf_event_nmi_handler) took too long to run',
                    run.Raw('|'),
                    'grep', '-v', 'INFO: recovery required on readonly',
                    run.Raw('|'),
                    'grep', '-v', 'ceph-create-keys: INFO',
                    run.Raw('|'),
                    'head', '-n', '1',
                ],
                stdout=StringIO(),
            )
            stdout = r.stdout.getvalue()
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
            ),
        )


def vm_setup(ctx, config):
    """
    Look for virtual machines and handle their initialization
    """
    all_tasks = [x.keys()[0] for x in ctx.config['tasks']]
    need_ansible = False
    if 'kernel' in all_tasks and 'ansible.cephlab' not in all_tasks:
        need_ansible = True
    ansible_hosts = set()
    with parallel():
        editinfo = os.path.join(os.path.dirname(__file__), 'edit_sudoers.sh')
        for rem in ctx.cluster.remotes.iterkeys():
            if misc.is_vm(rem.shortname):
                ansible_hosts.add(rem.shortname)
                r = rem.run(args=['test', '-e', '/ceph-qa-ready'],
                            stdout=StringIO(), check_status=False)
                if r.returncode != 0:
                    p1 = subprocess.Popen(['cat', editinfo],
                                          stdout=subprocess.PIPE)
                    p2 = subprocess.Popen(
                        [
                            'ssh',
                            '-o', 'StrictHostKeyChecking=no',
                            '-t', '-t',
                            str(rem),
                            'sudo',
                            'sh'
                        ],
                        stdin=p1.stdout, stdout=subprocess.PIPE
                    )
                    _, err = p2.communicate()
                    if err:
                        log.error("Edit of /etc/sudoers failed: %s", err)
    if need_ansible and ansible_hosts:
        log.info("Running ansible on %s", list(ansible_hosts))
        ansible_config = dict(
            hosts=list(ansible_hosts),
        )
        with ansible.CephLab(ctx, config=ansible_config):
            pass
