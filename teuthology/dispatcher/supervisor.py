import datetime
import logging
import os
import subprocess
import time
import yaml
import requests

from urllib.parse import urljoin

from teuthology import exporter, dispatcher, kill, report, safepath
from teuthology.config import config as teuth_config
from teuthology.exceptions import SkipJob, MaxWhileTries
from teuthology import setup_log_file, install_except_hook
from teuthology.misc import get_user, archive_logs, compress_logs
from teuthology.config import FakeNamespace
from teuthology.lock import ops as lock_ops
from teuthology.task import internal
from teuthology.misc import decanonicalize_hostname as shortname
from teuthology.lock import query
from teuthology.util import sentry

log = logging.getLogger(__name__)


def main(args):
    with open(args.job_config, 'r') as config_file:
        job_config = yaml.safe_load(config_file)

    loglevel = logging.INFO
    if args.verbose:
        loglevel = logging.DEBUG
    logging.getLogger().setLevel(loglevel)
    log.setLevel(loglevel)

    log_file_path = os.path.join(job_config['archive_path'],
                                 f"supervisor.{job_config['job_id']}.log")
    setup_log_file(log_file_path)
    install_except_hook()
    try:
        dispatcher.check_job_expiration(job_config)
    except SkipJob:
        return 0

    # reimage target machines before running the job
    if 'targets' in job_config:
        node_count = len(job_config["targets"])
        # If a job (e.g. from the nop suite) doesn't need nodes, avoid
        # submitting a zero here.
        if node_count:
            with exporter.NodeReimagingTime().time(
                machine_type=job_config["machine_type"],
                node_count=node_count,
            ):
                reimage(job_config)
        else:
            reimage(job_config)
        with open(args.job_config, 'w') as f:
            yaml.safe_dump(job_config, f, default_flow_style=False)

    suite = job_config.get("suite")
    if suite:
        with exporter.JobTime().time(suite=suite):
            return run_job(
                job_config,
                args.bin_path,
                args.archive_dir,
                args.verbose
            )
    else:
        return run_job(
            job_config,
            args.bin_path,
            args.archive_dir,
            args.verbose
        )


def run_job(job_config, teuth_bin_path, archive_dir, verbose):
    safe_archive = safepath.munge(job_config['name'])
    if job_config.get('first_in_suite') or job_config.get('last_in_suite'):
        job_archive = os.path.join(archive_dir, safe_archive)
        args = [
            os.path.join(teuth_bin_path, 'teuthology-results'),
            '--archive-dir', job_archive,
            '--name', job_config['name'],
        ]
        if job_config.get('first_in_suite'):
            log.info('Generating memo for %s', job_config['name'])
            if job_config.get('seed'):
                args.extend(['--seed', job_config['seed']])
            if job_config.get('subset'):
                args.extend(['--subset', job_config['subset']])
            if job_config.get('no_nested_subset'):
                args.extend(['--no-nested-subset'])
        else:
            log.info('Generating results for %s', job_config['name'])
            timeout = job_config.get('results_timeout',
                                     teuth_config.results_timeout)
            args.extend(['--timeout', str(timeout)])
            if job_config.get('email'):
                args.extend(['--email', job_config['email']])
        # Execute teuthology-results, passing 'preexec_fn=os.setpgrp' to
        # make sure that it will continue to run if this worker process
        # dies (e.g. because of a restart)
        result_proc = subprocess.Popen(args=args, preexec_fn=os.setpgrp)
        log.info("teuthology-results PID: %s", result_proc.pid)
        # Remove unnecessary logs for first and last jobs in run
        log.info('Deleting job\'s archive dir %s', job_config['archive_path'])
        for f in os.listdir(job_config['archive_path']):
            os.remove(os.path.join(job_config['archive_path'], f))
        os.rmdir(job_config['archive_path'])
        return

    log.info('Running job %s', job_config['job_id'])

    arg = [
        os.path.join(teuth_bin_path, 'teuthology'),
    ]
    # The following is for compatibility with older schedulers, from before we
    # started merging the contents of job_config['config'] into job_config
    # itself.
    if 'config' in job_config:
        inner_config = job_config.pop('config')
        if not isinstance(inner_config, dict):
            log.warning("run_job: job_config['config'] isn't a dict, it's a %s",
                     str(type(inner_config)))
        else:
            job_config.update(inner_config)

    if verbose or job_config['verbose']:
        arg.append('-v')

    arg.extend([
        '--owner', job_config['owner'],
        '--archive', job_config['archive_path'],
        '--name', job_config['name'],
    ])
    if job_config['description'] is not None:
        arg.extend(['--description', job_config['description']])
    job_archive = os.path.join(job_config['archive_path'], 'orig.config.yaml')
    arg.extend(['--', job_archive])

    log.debug("Running: %s" % ' '.join(arg))
    p = subprocess.Popen(
        args=arg,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.info("Job archive: %s", job_config['archive_path'])
    log.info("Job PID: %s", str(p.pid))

    if teuth_config.results_server:
        log.info("Running with watchdog")
        try:
            run_with_watchdog(p, job_config)
        except Exception:
            log.exception("run_with_watchdog had an unhandled exception")
            raise
    else:
        log.info("Running without watchdog")
        # This sleep() is to give the child time to start up and create the
        # archive dir.
        time.sleep(5)
        p.wait()

    if p.returncode != 0:
        log.error('Child exited with code %d', p.returncode)
    else:
        log.info('Success!')
    if 'targets' in job_config:
        unlock_targets(job_config)
    return p.returncode

def failure_is_reimage(failure_reason):
    if not failure_reason:
        return False
    reimage_failure = "Error reimaging machines:"
    if reimage_failure in failure_reason:
        return True
    else:
        return False


def check_for_reimage_failures_and_mark_down(targets, count=10):
    # Grab paddles history of jobs in the machine
    # and count the number of reimaging errors
    # if it fails N times then mark the machine down
    base_url = teuth_config.results_server
    for k, _ in targets.items():
        machine = k.split('@')[-1]
        url = urljoin(
            base_url,
            '/nodes/{0}/jobs/?count={1}'.format(machine, count)
        )
        resp = requests.get(url)
        jobs = resp.json()
        if len(jobs) < count:
            continue
        reimage_failures = list(filter(
            lambda j: failure_is_reimage(j['failure_reason']),
            jobs
        ))
        if len(reimage_failures) < count:
            continue
        # Mark machine down
        machine_name = shortname(k)
        lock_ops.update_lock(
            machine_name,
            description='reimage failed {0} times'.format(count),
            status='down',
        )
        log.error(
            'Reimage failed {0} times ... marking machine down'.format(count)
        )


def reimage(job_config):
    # Reimage the targets specified in job config
    # and update their keys in config after reimaging
    ctx = create_fake_context(job_config)
    # change the status during the reimaging process
    report.try_push_job_info(ctx.config, dict(status='waiting'))
    targets = job_config['targets']
    try:
        reimaged = lock_ops.reimage_machines(ctx, targets, job_config['machine_type'])
    except Exception as e:
        log.exception('Reimaging error. Nuking machines...')
        # Reimage failures should map to the 'dead' status instead of 'fail'
        report.try_push_job_info(
            ctx.config,
            dict(status='dead', failure_reason='Error reimaging machines: ' + str(e))
        )
        # There isn't an actual task called "reimage", but it doesn't seem
        # necessary to create a whole new Sentry tag for this.
        ctx.summary = {
            'sentry_event': sentry.report_error(job_config, e, task_name="reimage")
        }
        # Machine that fails to reimage after 10 times will be marked down
        check_for_reimage_failures_and_mark_down(targets)
        raise
    ctx.config['targets'] = reimaged
    # change the status to running after the reimaging process
    report.try_push_job_info(ctx.config, dict(status='running'))


def unlock_targets(job_config):
    serializer = report.ResultsSerializer(teuth_config.archive_base)
    job_info = serializer.job_info(job_config['name'], job_config['job_id'])
    machine_statuses = query.get_statuses(job_info['targets'].keys())
    # only unlock targets if locked and description matches
    locked = []
    for status in machine_statuses:
        name = shortname(status['name'])
        description = status['description']
        if not status['locked']:
            continue
        if description != job_info['archive_path']:
            log.warning(
                "Was going to unlock %s but it was locked by another job: %s",
                name, description
            )
            continue
        locked.append(name)
    if not locked:
        return
    if job_config.get("unlock_on_failure", True):
        log.info('Unlocking machines...')
        lock_ops.unlock_safe(locked, job_info["owner"], job_info["name"], job_info["job_id"])


def run_with_watchdog(process, job_config):
    job_start_time = datetime.datetime.now(datetime.timezone.utc)

    # Only push the information that's relevant to the watchdog, to save db
    # load
    job_info = dict(
        name=job_config['name'],
        job_id=job_config['job_id'],
    )

    # Sleep once outside of the loop to avoid double-posting jobs
    time.sleep(teuth_config.watchdog_interval)
    hit_max_timeout = False
    while process.poll() is None:
        # Kill jobs that have been running longer than the global max
        run_time = datetime.datetime.now(datetime.timezone.utc) - job_start_time
        total_seconds = run_time.days * 60 * 60 * 24 + run_time.seconds
        if total_seconds > teuth_config.max_job_time:
            hit_max_timeout = True
            log.warning("Job ran longer than {max}s. Killing...".format(
                max=teuth_config.max_job_time))
            try:
                # kill processes but do not unlock yet so we can save
                # the logs, coredumps, etc.
                kill.kill_job(
                    job_info['name'], job_info['job_id'],
                    teuth_config.archive_base, job_config['owner'],
                    skip_unlock=True
                )
            except Exception:
                log.exception('Failed to kill job')

            try:
                transfer_archives(job_info['name'], job_info['job_id'],
                                  teuth_config.archive_base, job_config)
            except Exception:
                log.exception('Could not save logs')

            try:
                # this time remove everything and unlock the machines
                kill.kill_job(
                    job_info['name'], job_info['job_id'],
                    teuth_config.archive_base, job_config['owner']
                )
            except Exception:
                log.exception('Failed to kill job and unlock machines')

        # calling this without a status just updates the jobs updated time
        try:
            report.try_push_job_info(job_info)
        except MaxWhileTries:
            log.exception("Failed to report job status; ignoring")
        time.sleep(teuth_config.watchdog_interval)

    # we no longer support testing theses old branches
    assert(job_config.get('teuthology_branch') not in ('argonaut', 'bobtail',
                                                       'cuttlefish', 'dumpling'))

    # Let's make sure that paddles knows the job is finished. We don't know
    # the status, but if it was a pass or fail it will have already been
    # reported to paddles. In that case paddles ignores the 'dead' status.
    # If the job was killed, paddles will use the 'dead' status.
    extra_info = dict(status='dead')
    if hit_max_timeout:
        extra_info['failure_reason'] = 'hit max job timeout'
    if not (job_config.get('first_in_suite') or job_config.get('last_in_suite')):
        report.try_push_job_info(job_info, extra_info)


def create_fake_context(job_config, block=False):
    owner = job_config.get('owner', get_user())
    os_version = job_config.get('os_version', None)

    ctx_args = {
        'config': job_config,
        'block': block,
        'owner': owner,
        'archive': job_config['archive_path'],
        'machine_type': job_config['machine_type'],
        'os_type': job_config.get('os_type', 'ubuntu'),
        'os_version': os_version,
        'name': job_config['name'],
        'job_id': job_config['job_id'],
    }

    return FakeNamespace(ctx_args)


def transfer_archives(run_name, job_id, archive_base, job_config):
    serializer = report.ResultsSerializer(archive_base)
    job_info = serializer.job_info(run_name, job_id, simple=True)

    if 'archive' in job_info:
        ctx = create_fake_context(job_config)
        internal.add_remotes(ctx, job_config)

        for log_type, log_path in job_info['archive'].items():
            if log_type == 'init':
                log_type = ''
            compress_logs(ctx, log_path)
            archive_logs(ctx, log_path, log_type)
    else:
        log.info('No archives to transfer.')
