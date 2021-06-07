import logging
import pprint
import sys
from collections import OrderedDict

from teuthology import report
from teuthology.config import config


log = logging.getLogger(__name__)


def connect():
    host = config.queue_host
    port = config.queue_port
    if host is None or port is None:
        raise RuntimeError(
            'Beanstalk queue information not found in {conf_path}'.format(
                conf_path=config.teuthology_yaml))
    return beanstalkc.Connection(host=host, port=port, parse_yaml=yaml.safe_load)


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

def stats_queue(machine_type):
    stats = report.get_queue_stats(machine_type)
    stats = report.get_queue_stats(machine_type)
    if stats['paused'] is None:
        log.info("%s queue is currently running with %s jobs queued",
                 stats['name'],
                 stats['count'])
    else:
        log.info("%s queue is paused with %s jobs queued",
                 stats['name'],
                 stats['count'])


def update_priority(machine_type, priority, user):
    jobs = report.get_user_jobs_queue(machine_type, user)
    for job in jobs:
        job['priority'] = priority
        report.try_push_job_info(job)


def pause_queue(machine_type, pause_duration, paused_by):
    report.pause_queue(machine_type, paused_by, pause_duration)


def print_progress(index, total, message=None):
    msg = "{m} ".format(m=message) if message else ''
    sys.stderr.write("{msg}{i}/{total}\r".format(
        msg=msg, i=index, total=total))
    sys.stderr.flush()


def end_progress():
    sys.stderr.write('\n')
    sys.stderr.flush()


def walk_jobs(machine_type, processor, user):
    log.info("Checking paddles queue...")
    job_count = report.get_queue_stats(machine_type)['count']

    jobs = report.get_user_jobs_queue(machine_type, user)
    if job_count == 0:
        log.info('No jobs in queue')
        return

    for i in range(1, job_count + 1):
        print_progress(i, job_count, "Loading")
        job = jobs[i-1]
        if job is None:
            continue
        job_id = job['job_id']
        processor.add_job(job_id, job)
    end_progress()
    processor.complete()


class JobProcessor(object):
    def __init__(self):
        self.jobs = OrderedDict()

    def add_job(self, job_id, job_config, job_obj=None):
        job_id = str(job_id)

        job_dict = dict(
            index=(len(self.jobs) + 1),
            job_config=job_config,
        )
        if job_obj:
            job_dict['job_obj'] = job_obj
        self.jobs[job_id] = job_dict

        self.process_job(job_id)

    def process_job(self, job_id):
        pass

    def complete(self):
        pass


class JobPrinter(JobProcessor):
    def __init__(self, show_desc=False, full=False):
        super(JobPrinter, self).__init__()
        self.show_desc = show_desc
        self.full = full

    def process_job(self, job_id):
        job_config = self.jobs[job_id]['job_config']
        job_index = self.jobs[job_id]['index']
        job_priority = job_config['priority']
        job_name = job_config['name']
        job_desc = job_config['description']
        print('Job: {i:>4} priority: {pri:>4} {job_name}/{job_id}'.format(
            i=job_index,
            pri=job_priority,
            job_id=job_id,
            job_name=job_name,
            ))
        if self.full:
            pprint.pprint(job_config)
        elif job_desc and self.show_desc:
            for desc in job_desc.split():
                print('\t {}'.format(desc))


class RunPrinter(JobProcessor):
    def __init__(self):
        super(RunPrinter, self).__init__()
        self.runs = list()

    def process_job(self, job_id):
        run = self.jobs[job_id]['job_config']['name']
        if run not in self.runs:
            self.runs.append(run)
            print(run)


class JobDeleter(JobProcessor):
    def __init__(self, pattern):
        self.pattern = pattern
        super(JobDeleter, self).__init__()

    def add_job(self, job_id, job_config, job_obj=None):
        job_name = job_config['name']
        if self.pattern in job_name:
            super(JobDeleter, self).add_job(job_id, job_config, job_obj)

    def process_job(self, job_id):
        job_config = self.jobs[job_id]['job_config']
        job_name = job_config['name']
        print('Deleting {job_name}/{job_id}'.format(
            job_id=job_id,
            job_name=job_name,
            ))
        report.try_delete_jobs(job_name, job_id)


def main(args):
    machine_type = args['--machine_type']
    user = args['--user']
    priority = args['--priority']
    status = args['--status']
    delete = args['--delete']
    runs = args['--runs']
    show_desc = args['--description']
    full = args['--full']
    pause_duration = args['--pause']
    try:
        if status:
            stats_queue(machine_type)
        elif pause_duration:
            pause_queue(machine_type, pause_duration, user)
        elif priority:
            update_priority(machine_type, priority, user)
        elif delete:
            walk_jobs(machine_type,
                      JobDeleter(delete), user)
        elif runs:
            walk_jobs(machine_type,
                      RunPrinter(), user)
        else:
            walk_jobs(machine_type,
                      JobPrinter(show_desc=show_desc, full=full),
                      user)
    except KeyboardInterrupt:
        log.info("Interrupted.")
