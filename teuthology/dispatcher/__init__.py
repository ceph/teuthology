import logging
import os
import subprocess
import sys
import yaml
import tempfile

from datetime import datetime

from teuthology import setup_log_file, install_except_hook
from teuthology import beanstalk
from teuthology import report
from teuthology import safepath
from teuthology.config import config as teuth_config
from teuthology.config import set_config_attr
from teuthology.exceptions import BranchNotFoundError, SkipJob, MaxWhileTries
from teuthology.repo_utils import fetch_qa_suite, fetch_teuthology
from teuthology.misc import get_user
from teuthology.config import FakeNamespace
from teuthology.task.internal.lock_machines import lock_machines_helper

log = logging.getLogger(__name__)
start_time = datetime.utcnow()
restart_file_path = '/tmp/teuthology-restart-workers'
stop_file_path = '/tmp/teuthology-stop-workers'


def sentinel(path):
    if not os.path.exists(path):
        return False
    file_mtime = datetime.utcfromtimestamp(os.path.getmtime(path))
    if file_mtime > start_time:
        return True
    else:
        return False


def restart():
    log.info('Restarting...')
    args = sys.argv[:]
    args.insert(0, sys.executable)
    os.execv(sys.executable, args)


def stop():
    log.info('Stopping...')
    sys.exit(0)


def load_config(ctx=None):
    teuth_config.load()
    if ctx is not None:
        if not os.path.isdir(ctx.archive_dir):
            sys.exit("{prog}: archive directory must exist: {path}".format(
                prog=os.path.basename(sys.argv[0]),
                path=ctx.archive_dir,
            ))
        else:
            teuth_config.archive_base = ctx.archive_dir


def main(ctx):
    loglevel = logging.INFO
    if ctx.verbose:
        loglevel = logging.DEBUG
    log.setLevel(loglevel)

    log_file_path = os.path.join(ctx.log_dir, 'dispatcher.{tube}.{pid}'.format(
        pid=os.getpid(), tube=ctx.tube,))
    setup_log_file(log_file_path)

    install_except_hook()

    load_config(ctx=ctx)

    set_config_attr(ctx)

    connection = beanstalk.connect()
    beanstalk.watch_tube(connection, ctx.tube)
    result_proc = None

    if teuth_config.teuthology_path is None:
        fetch_teuthology('master')
    fetch_qa_suite('master')

    keep_running = True
    while keep_running:
        # Check to see if we have a teuthology-results process hanging around
        # and if so, read its return code so that it can exit.
        if result_proc is not None and result_proc.poll() is not None:
            log.debug("teuthology-results exited with code: %s",
                      result_proc.returncode)
            result_proc = None

        if sentinel(restart_file_path):
            restart()
        elif sentinel(stop_file_path):
            stop()

        load_config()

        job = connection.reserve(timeout=60)
        if job is None:
            continue

        # bury the job so it won't be re-run if it fails
        job.bury()
        job_id = job.jid
        log.info('Reserved job %d', job_id)
        log.info('Config is: %s', job.body)
        job_config = yaml.safe_load(job.body)
        job_config['job_id'] = str(job_id)

        if job_config.get('stop_worker'):
            keep_running = False

        job_config, teuth_bin_path = prep_job(
            job_config,
            log_file_path,
            ctx.archive_dir,
        )
        if not job_config.get('first_in_suite') \
                and not job_config.get('last_in_suite') \
                and 'roles' in job_config:
            job_config = lock_machines(job_config)

        run_args = [
            os.path.join(teuth_bin_path, 'teuthology-worker'),
            '-v',
            '--bin-path', teuth_bin_path,
            '--archive-dir', ctx.archive_dir,
        ]

        with tempfile.NamedTemporaryFile(prefix='teuthology-worker.',
                                         suffix='.tmp', mode='w+t') as tmp:
            yaml.safe_dump(data=job_config, stream=tmp)
            tmp.flush()
            run_args.extend(["--config-fd", str(tmp.fileno())])
            job_proc = subprocess.Popen(run_args, pass_fds=[tmp.fileno()])

        log.info('Job subprocess PID: %s', job_proc.pid)

        # This try/except block is to keep the worker from dying when
        # beanstalkc throws a SocketError
        try:
            job.delete()
        except Exception:
            log.exception("Saw exception while trying to delete job")


def prep_job(job_config, log_file_path, archive_dir):
    job_id = job_config['job_id']
    safe_archive = safepath.munge(job_config['name'])
    job_config['worker_log'] = log_file_path
    archive_path_full = os.path.join(
        archive_dir, safe_archive, str(job_id))
    job_config['archive_path'] = archive_path_full

    # If the teuthology branch was not specified, default to master and
    # store that value.
    teuthology_branch = job_config.get('teuthology_branch', 'master')
    job_config['teuthology_branch'] = teuthology_branch

    try:
        if teuth_config.teuthology_path is not None:
            teuth_path = teuth_config.teuthology_path
        else:
            teuth_path = fetch_teuthology(branch=teuthology_branch)
        # For the teuthology tasks, we look for suite_branch, and if we
        # don't get that, we look for branch, and fall back to 'master'.
        # last-in-suite jobs don't have suite_branch or branch set.
        ceph_branch = job_config.get('branch', 'master')
        suite_branch = job_config.get('suite_branch', ceph_branch)
        suite_repo = job_config.get('suite_repo')
        if suite_repo:
            teuth_config.ceph_qa_suite_git_url = suite_repo
        job_config['suite_path'] = os.path.normpath(os.path.join(
            fetch_qa_suite(suite_branch),
            job_config.get('suite_relpath', ''),
        ))
    except BranchNotFoundError as exc:
        log.exception("Branch not found; marking job as dead")
        report.try_push_job_info(
            job_config,
            dict(status='dead', failure_reason=str(exc))
        )
        raise SkipJob()
    except MaxWhileTries as exc:
        log.exception("Failed to fetch or bootstrap; marking job as dead")
        report.try_push_job_info(
            job_config,
            dict(status='dead', failure_reason=str(exc))
        )
        raise SkipJob()

    teuth_bin_path = os.path.join(teuth_path, 'virtualenv', 'bin')
    if not os.path.isdir(teuth_bin_path):
        raise RuntimeError("teuthology branch %s at %s not bootstrapped!" %
                           (teuthology_branch, teuth_bin_path))
    return job_config, teuth_bin_path


def lock_machines(job_config):
    fake_ctx = create_fake_context(job_config, block=True)
    lock_machines_helper(fake_ctx, [len(job_config['roles']),
                         job_config['machine_type']])
    job_config = fake_ctx.config
    return job_config


def create_fake_context(job_config, block=False):
    if job_config['owner'] is None:
        job_config['owner'] = get_user()

    if 'os_version' in job_config:
        os_version = job_config['os_version']
    else:
        os_version = None

    ctx_args = {
        'config': job_config,
        'block': block,
        'owner': job_config['owner'],
        'archive': job_config['archive_path'],
        'machine_type': job_config['machine_type'],
        'os_type': job_config['os_type'],
        'os_version': os_version,
    }

    fake_ctx = FakeNamespace(ctx_args)
    return fake_ctx
