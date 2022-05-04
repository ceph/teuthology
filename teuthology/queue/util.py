import logging
import pprint
import sys
from collections import OrderedDict

from teuthology import report

log = logging.getLogger(__name__)


def print_progress(index, total, message=None):
    msg = "{m} ".format(m=message) if message else ''
    sys.stderr.write("{msg}{i}/{total}\r".format(
        msg=msg, i=index, total=total))
    sys.stderr.flush()


def end_progress():
    sys.stderr.write('\n')
    sys.stderr.flush()


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
