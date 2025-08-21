import datetime
import logging
import os
import psutil
import subprocess
import sys
import yaml

from typing import Dict, List

from teuthology import (
    # non-modules
    setup_log_file,
    install_except_hook,
    # modules
    beanstalk,
    exporter,
    report,
    repo_utils,
)
from teuthology.config import config as teuth_config
from teuthology.dispatcher import supervisor
from teuthology.exceptions import BranchNotFoundError, CommitNotFoundError, SkipJob, MaxWhileTries
from teuthology.lock import ops as lock_ops
from teuthology.util.time import parse_timestamp
from teuthology import safepath

log = logging.getLogger(__name__)
start_time = datetime.datetime.now(datetime.timezone.utc)
restart_file_path = '/tmp/teuthology-restart-dispatcher'
stop_file_path = '/tmp/teuthology-stop-dispatcher'


def sentinel(path):
    if not os.path.exists(path):
        return False
    file_mtime = datetime.datetime.fromtimestamp(
        os.path.getmtime(path),
        datetime.timezone.utc,
    )
    return file_mtime > start_time


def restart(log=log):
    log.info('Restarting...')
    args = sys.argv[:]
    args.insert(0, sys.executable)
    os.execv(sys.executable, args)


def stop():
    log.info('Stopping...')
    sys.exit(0)


def load_config(archive_dir=None):
    teuth_config.load()
    if archive_dir is not None:
        if not os.path.isdir(archive_dir):
            sys.exit("{prog}: archive directory must exist: {path}".format(
                prog=os.path.basename(sys.argv[0]),
                path=archive_dir,
            ))
        else:
            teuth_config.archive_base = archive_dir


def main(args):
    archive_dir = args.archive_dir or teuth_config.archive_base

    # Refuse to start more than one dispatcher per machine type
    procs = find_dispatcher_processes().get(args.tube)
    if procs:
        raise RuntimeError(
            "There is already a teuthology-dispatcher process running:"
            f" {procs}"
        )

    # setup logging for disoatcher in {log_dir}
    loglevel = logging.INFO
    if args.verbose:
        loglevel = logging.DEBUG
    logging.getLogger().setLevel(loglevel)
    log.setLevel(loglevel)
    log_file_path = os.path.join(args.log_dir, f"dispatcher.{args.tube}.{os.getpid()}")
    setup_log_file(log_file_path)
    install_except_hook()

    load_config(archive_dir=archive_dir)

    connection = beanstalk.connect()
    beanstalk.watch_tube(connection, args.tube)
    result_proc = None

    if teuth_config.teuthology_path is None:
        repo_utils.fetch_teuthology('main')
    repo_utils.fetch_qa_suite('main')

    keep_running = True
    job_procs = set()
    worst_returncode = 0
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
        for proc in list(job_procs):
            rc = proc.poll()
            if rc is not None:
                worst_returncode = max([worst_returncode, rc])
                job_procs.remove(proc)
        job = connection.reserve(timeout=60)
        if job is None:
            if args.exit_on_empty_queue and not job_procs:
                log.info("Queue is empty and no supervisor processes running; exiting!")
                break
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

        try:
            job_config, teuth_bin_path = prep_job(
                job_config,
                log_file_path,
                archive_dir,
            )
        except SkipJob:
            continue

        # lock machines but do not reimage them
        if 'roles' in job_config:
            job_config = lock_machines(job_config)

        run_args = [
            os.path.join(teuth_bin_path, 'teuthology-supervisor'),
            '-v',
            '--bin-path', teuth_bin_path,
            '--archive-dir', archive_dir,
        ]

        # Create run archive directory if not already created and
        # job's archive directory
        create_job_archive(job_config['name'],
                           job_config['archive_path'],
                           archive_dir)
        job_config_path = os.path.join(job_config['archive_path'], 'orig.config.yaml')

        # Write initial job config in job archive dir
        with open(job_config_path, 'w') as f:
            yaml.safe_dump(job_config, f, default_flow_style=False)

        run_args.extend(["--job-config", job_config_path])

        try:
            job_proc = subprocess.Popen(
                run_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            job_procs.add(job_proc)
            log.info('Job supervisor PID: %s', job_proc.pid)
        except Exception:
            error_message = "Saw error while trying to spawn supervisor."
            log.exception(error_message)
            if 'targets' in job_config:
                node_names = job_config["targets"].keys()
                lock_ops.unlock_safe(
                    node_names,
                    job_config["owner"],
                    job_config["name"],
                    job_config["job_id"]
                )
            report.try_push_job_info(job_config, dict(
                status='fail',
                failure_reason=error_message))

        # This try/except block is to keep the worker from dying when
        # beanstalkc throws a SocketError
        try:
            job.delete()
        except Exception:
            log.exception("Saw exception while trying to delete job")

    return worst_returncode


def find_dispatcher_processes() -> Dict[str, List[psutil.Process]]:
    def match(proc):
        try:
            cmdline = proc.cmdline()
        except psutil.AccessDenied:
            return False
        except psutil.ZombieProcess:
            return False
        if len(cmdline) < 3:
            return False
        if not cmdline[1].endswith("/teuthology-dispatcher"):
            return False
        if cmdline[2] == "--supervisor":
            return False
        if "--tube" not in cmdline:
            return False
        if proc.pid == os.getpid():
            return False
        return True

    procs = {}
    attrs = ["pid", "cmdline"]
    for proc in psutil.process_iter(attrs=attrs):
        if not match(proc):
            continue
        cmdline = proc.cmdline()
        machine_type = cmdline[cmdline.index("--tube") + 1]
        procs.setdefault(machine_type, []).append(proc)
    return procs


def prep_job(job_config, log_file_path, archive_dir):
    job_id = job_config['job_id']
    check_job_expiration(job_config)

    safe_archive = safepath.munge(job_config['name'])
    job_config['worker_log'] = log_file_path
    archive_path_full = os.path.join(
        archive_dir, safe_archive, str(job_id))
    job_config['archive_path'] = archive_path_full

    # If the teuthology branch was not specified, default to main and
    # store that value.
    teuthology_branch = job_config.get('teuthology_branch', 'main')
    job_config['teuthology_branch'] = teuthology_branch
    teuthology_repo = job_config.get('teuthology_repo')
    if teuthology_repo:
        teuth_config.teuthology_git_url = teuthology_repo
    teuthology_sha1 = job_config.get('teuthology_sha1')
    if not teuthology_sha1:
        repo_url = teuth_config.get_teuthology_git_url()
        try:
            teuthology_sha1 = repo_utils.ls_remote(repo_url, teuthology_branch)
        except Exception as exc:
            log.exception(f"Could not get teuthology sha1 for branch {teuthology_branch}")
            report.try_push_job_info(
                job_config,
                dict(status='dead', failure_reason=str(exc))
            )
            raise SkipJob()
        if not teuthology_sha1:
            reason = "Teuthology branch {} not found; marking job as dead".format(teuthology_branch)
            log.error(reason)
            report.try_push_job_info(
                job_config,
                dict(status='dead', failure_reason=reason)
            )
            raise SkipJob()
        if teuth_config.teuthology_path is None:
            log.info('Using teuthology sha1 %s', teuthology_sha1)

    try:
        if teuth_config.teuthology_path is not None:
            teuth_path = teuth_config.teuthology_path
        else:
            teuth_path = repo_utils.fetch_teuthology(branch=teuthology_branch,
                                          commit=teuthology_sha1)
        # For the teuthology tasks, we look for suite_branch, and if we
        # don't get that, we look for branch, and fall back to 'main'.
        # last-in-suite jobs don't have suite_branch or branch set.
        ceph_branch = job_config.get('branch', 'main')
        suite_branch = job_config.get('suite_branch', ceph_branch)
        suite_sha1 = job_config.get('suite_sha1')
        suite_repo = job_config.get('suite_repo')
        if suite_repo:
            teuth_config.ceph_qa_suite_git_url = suite_repo
        job_config['suite_path'] = os.path.normpath(os.path.join(
            repo_utils.fetch_qa_suite(suite_branch, suite_sha1),
            job_config.get('suite_relpath', ''),
        ))
    except (BranchNotFoundError, CommitNotFoundError) as exc:
        log.exception("Requested version not found; marking job as dead")
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


def check_job_expiration(job_config):
    job_id = job_config['job_id']
    expired = False
    now = datetime.datetime.now(datetime.timezone.utc)
    if expire_str := job_config.get('timestamp'):
        expire = parse_timestamp(expire_str) + \
            datetime.timedelta(seconds=teuth_config.max_job_age)
        expired = expire < now
    if not expired and (expire_str := job_config.get('expire')):
        try:
            expire = parse_timestamp(expire_str)
            expired = expired or expire < now
        except ValueError:
            log.warning(f"Failed to parse job expiration: {expire_str=}")
            pass
    if expired:
        log.info(f"Skipping job {job_id} because it is expired: {expire_str} is in the past")
        report.try_push_job_info(
            job_config,
            # TODO: Add a 'canceled' status to paddles, and use that.
            dict(status='dead'),
        )
        raise SkipJob()


def lock_machines(job_config):
    report.try_push_job_info(job_config, dict(status='running'))
    fake_ctx = supervisor.create_fake_context(job_config, block=True)
    machine_type = job_config["machine_type"]
    count = len(job_config['roles'])
    with exporter.NodeLockingTime().time(
        machine_type=machine_type,
        count=count,
    ):
        lock_ops.block_and_lock_machines(
            fake_ctx,
            count,
            machine_type,
            tries=-1,
            reimage=False,
        )
    job_config = fake_ctx.config
    return job_config


def create_job_archive(job_name, job_archive_path, archive_dir):
    log.info('Creating job\'s archive dir %s', job_archive_path)
    safe_archive = safepath.munge(job_name)
    run_archive = os.path.join(archive_dir, safe_archive)
    if not os.path.exists(run_archive):
        safepath.makedirs('/', run_archive)
    safepath.makedirs('/', job_archive_path)
