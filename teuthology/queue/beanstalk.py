import beanstalkc
import yaml
import logging
import pprint
import sys
from collections import OrderedDict

from teuthology.config import config
from teuthology import report

log = logging.getLogger(__name__)


def connect():
    host = config.queue_host
    port = config.queue_port
    if host is None or port is None:
        raise RuntimeError(
            'Beanstalk queue information not found in {conf_path}'.format(
                conf_path=config.teuthology_yaml))
    return beanstalkc.Connection(host=host, port=port)


def watch_tube(connection, tube_name):
    """
    Watch a given tube, potentially correcting to 'multi' if necessary. Returns
    the tube_name that was actually used.
    """
    if ',' in tube_name:
        log.debug("Correcting tube name to 'multi'")
        tube_name = 'multi'
    connection.watch(tube_name)
    connection.ignore('default')
    return tube_name


def walk_jobs(connection, tube_name, processor, pattern=None):
    """
    def callback(jobs_dict)
    """
    log.info("Checking Beanstalk Queue...")
    job_count = connection.stats_tube(tube_name)['current-jobs-ready']
    if job_count == 0:
        log.info('No jobs in Beanstalk Queue')
        return

    # Try to figure out a sane timeout based on how many jobs are in the queue
    timeout = job_count / 2000.0 * 60
    for i in range(1, job_count + 1):
        print_progress(i, job_count, "Loading")
        job = connection.reserve(timeout=timeout)
        if job is None or job.body is None:
            continue
        job_config = yaml.safe_load(job.body)
        job_name = job_config['name']
        job_id = job.stats()['id']
        if pattern is not None and pattern not in job_name:
            continue
        processor.add_job(job_id, job_config, job)
    end_progress()
    processor.complete()


def pause_tube(connection, tube, duration):
    duration = int(duration)
    if not tube:
        tubes = sorted(connection.tubes())
    else:
        tubes = [tube]

    prefix = 'Unpausing' if duration == 0 else "Pausing for {dur}s"
    templ = prefix + ": {tubes}"
    log.info(templ.format(dur=duration, tubes=tubes))
    for tube in tubes:
        connection.pause_tube(tube, duration)


def stats_tube(connection, tube):
    stats = connection.stats_tube(tube)
    result = dict(
        name=tube,
        count=stats['current-jobs-ready'],
        paused=(stats['pause'] != 0),
    )
    return result


def main(args):
    machine_type = args['--machine_type']
    status = args['--status']
    delete = args['--delete']
    runs = args['--runs']
    show_desc = args['--description']
    full = args['--full']
    pause_duration = args['--pause']
    try:
        connection = connect()
        if machine_type and not pause_duration:
            # watch_tube needs to be run before we inspect individual jobs;
            # it is not needed for pausing tubes
            watch_tube(connection, machine_type)
        if status:
            print(stats_tube(connection, machine_type))
        elif pause_duration:
            pause_tube(connection, machine_type, pause_duration)
        elif delete:
            walk_jobs(connection, machine_type,
                      JobDeleter(delete))
        elif runs:
            walk_jobs(connection, machine_type,
                      RunPrinter())
        else:
            walk_jobs(connection, machine_type,
                      JobPrinter(show_desc=show_desc, full=full))
    except KeyboardInterrupt:
        log.info("Interrupted.")
    finally:
        connection.close()
