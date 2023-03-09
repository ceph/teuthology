import logging
import os
import psutil
import subprocess
import sys
import yaml

from datetime import datetime
from typing import Dict, List

import teuthology.dispatcher.supervisor as supervisor
import teuthology.exporter as exporter
import teuthology.lock.ops as lock_ops
import teuthology.nuke as nuke
import teuthology.repo_utils as repo_utils
import teuthology.worker as worker

from teuthology import setup_log_file, install_except_hook
from teuthology import beanstalk
from teuthology import report
from teuthology.config import config as teuth_config
from teuthology.exceptions import SkipJob
from teuthology import safepath

log = logging.getLogger(__name__)
start_time = datetime.utcnow()
restart_file_path = '/tmp/teuthology-restart-dispatcher'
stop_file_path = '/tmp/teuthology-stop-dispatcher'


def sentinel(path):
    if not os.path.exists(path):
        return False
    file_mtime = datetime.utcfromtimestamp(os.path.getmtime(path))
    return file_mtime > start_time


def restart():
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
    # run dispatcher in job supervisor mode if --supervisor passed
    if args["--supervisor"]:
        return supervisor.main(args)

    verbose = args["--verbose"]
    tube = args["--tube"]
    log_dir = args["--log-dir"]
    archive_dir = args["--archive-dir"]
    exit_on_empty_queue = args["--exit-on-empty-queue"]

    if archive_dir is None:
        archive_dir = teuth_config.archive_base

    # Refuse to start more than one dispatcher per machine type
    procs = find_dispatcher_processes().get(tube)
    if procs:
        raise RuntimeError(
            "There is already a teuthology-dispatcher process running:"
            f" {procs}"
        )

    # setup logging for disoatcher in {log_dir}
    loglevel = logging.INFO
    if verbose:
        loglevel = logging.DEBUG
    log.setLevel(loglevel)
    log_file_path = os.path.join(log_dir, f"dispatcher.{tube}.{os.getpid()}")
    setup_log_file(log_file_path)
    install_except_hook()

    load_config(archive_dir=archive_dir)

    connection = beanstalk.connect()
    beanstalk.watch_tube(connection, tube)
    result_proc = None

    if teuth_config.teuthology_path is None:
        repo_utils.fetch_teuthology('main')
    repo_utils.fetch_qa_suite('main')

    keep_running = True
    job_procs = set()
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
        job_procs = set(filter(lambda p: p.poll() is None, job_procs))
        job = connection.reserve(timeout=60)
        if job is None:
            if exit_on_empty_queue and not job_procs:
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
            job_config, teuth_bin_path = worker.prep_job(
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
            os.path.join(teuth_bin_path, 'teuthology-dispatcher'),
            '--supervisor',
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
            job_proc = subprocess.Popen(run_args)
            job_procs.add(job_proc)
            log.info('Job supervisor PID: %s', job_proc.pid)
        except Exception:
            error_message = "Saw error while trying to spawn supervisor."
            log.exception(error_message)
            if 'targets' in job_config:
                nuke.nuke(supervisor.create_fake_context(job_config), True)
            report.try_push_job_info(job_config, dict(
                status='fail',
                failure_reason=error_message))

        # This try/except block is to keep the worker from dying when
        # beanstalkc throws a SocketError
        try:
            job.delete()
        except Exception:
            log.exception("Saw exception while trying to delete job")

    returncodes = set([0])
    for proc in job_procs:
        if proc.returncode is not None:
            returncodes.add(proc.returncode)
    return max(returncodes)


def find_dispatcher_processes() -> Dict[str, List[psutil.Process]]:
    def match(proc):
        cmdline = proc.cmdline()
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


def lock_machines(job_config):
    report.try_push_job_info(job_config, dict(status='running'))
    fake_ctx = supervisor.create_fake_context(job_config, block=True)
    machine_type = job_config["machine_type"]
    count = len(job_config['roles'])
    with exporter.NodeLockingTime.labels(machine_type, count).time():
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
