import datetime
import logging
import os
import yaml

from teuthology import (
    # non-modules
    setup_log_file,
    install_except_hook,
    # modules
    beanstalk,
    repo_utils,
)
from teuthology.config import config as teuth_config
from teuthology.config import set_config_attr
from teuthology.dispatcher import (
    load_config,
    prep_job,
    restart,
    restart_file_path,
    sentinel,
    stop,
    stop_file_path,
)
from teuthology.dispatcher.supervisor import run_job
from teuthology.exceptions import SkipJob

log = logging.getLogger(__name__)
start_time = datetime.datetime.now(datetime.timezone.utc)

def main(ctx):
    loglevel = logging.INFO
    if ctx.verbose:
        loglevel = logging.DEBUG
    log.setLevel(loglevel)

    log_file_path = os.path.join(ctx.log_dir, 'worker.{tube}.{pid}'.format(
        pid=os.getpid(), tube=ctx.tube,))
    setup_log_file(log_file_path)

    install_except_hook()

    load_config(ctx.archive_dir)

    set_config_attr(ctx)

    connection = beanstalk.connect()
    beanstalk.watch_tube(connection, ctx.tube)
    result_proc = None

    if teuth_config.teuthology_path is None:
        repo_utils.fetch_teuthology('main')
    repo_utils.fetch_qa_suite('main')

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

        try:
            job_config, teuth_bin_path = prep_job(
                job_config,
                log_file_path,
                ctx.archive_dir,
            )
            run_job(
                job_config,
                teuth_bin_path,
                ctx.archive_dir,
                ctx.verbose,
            )
        except SkipJob:
            continue

        # This try/except block is to keep the worker from dying when
        # beanstalkc throws a SocketError
        try:
            job.delete()
        except Exception:
            log.exception("Saw exception while trying to delete job")
