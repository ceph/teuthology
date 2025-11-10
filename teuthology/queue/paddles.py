import logging

from teuthology import report
from teuthology.queue import util

log = logging.getLogger(__name__)


def stats_queue(machine_type):
    stats = report.get_queue_stats(machine_type)
    if stats['paused'] is None:
        log.info("%s queue is currently running with %s jobs queued",
                 stats['queue'],
                 stats['queued_jobs'])
    else:
        log.info("%s queue is paused with %s jobs queued",
                 stats['queue'],
                 stats['queued_jobs'])


def update_priority(machine_type, priority, run_name=None):
    if run_name is not None:
        jobs = report.get_jobs_by_run(machine_type, run_name)
    for job in jobs:
        job['priority'] = priority
        report.try_push_job_info(job)


def walk_jobs(machine_type, processor, user):
    log.info("Checking paddles queue...")
    job_count = report.get_queue_stats(machine_type)['queued_jobs']

    jobs = report.get_user_jobs_queue(machine_type, user)
    if job_count == 0:
        log.info('No jobs in Paddles queue')
        return

    for i in range(1, job_count + 1):
        util.print_progress(i, job_count, "Loading")
        job = jobs[i-1]
        if job is None:
            continue
        job_id = job['job_id']
        processor.add_job(job_id, job)
    util.end_progress()
    processor.complete()


def main(args):
    machine_type = args['--machine_type']
    user = args['--user']
    run_name = args['--run-name']
    status = args['--status']
    delete = args['--delete']
    runs = args['--runs']
    show_desc = args['--description']
    full = args['--full']
    pause_duration = args['--pause']
    priority = args['--priority']
    try:
        if status:
            stats_queue(machine_type)
        if pause_duration:
            if not user:
                log.info('Please enter user to pause Paddles queue')
                return
            report.pause_queue(machine_type, user, pause_duration)
        elif priority:
            update_priority(machine_type, priority, run_name)
        elif delete:
            walk_jobs(machine_type,
                      util.JobDeleter(delete), user)
        elif runs:
            walk_jobs(machine_type,
                      util.RunPrinter(), user)
        else:
            walk_jobs(machine_type,
                      util.JobPrinter(show_desc=show_desc, full=full),
                      user)
    except KeyboardInterrupt:
        log.info("Interrupted.")
