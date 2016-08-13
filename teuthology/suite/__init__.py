# this file is responsible for submitting tests into the queue
# by generating combinations of facets found in
# https://github.com/ceph/ceph-qa-suite.git

import logging
import os
import time

import teuthology
from ..config import config, YamlConfig
from ..report import ResultsReporter
from ..results import UNFINISHED_STATUSES

from .run import Run
from .util import schedule_fail

log = logging.getLogger(__name__)


def process_args(args):
    conf = YamlConfig()
    rename_args = {
        'ceph': 'ceph_branch',
        'sha1': 'ceph_sha1',
        'kernel': 'kernel_branch',
        # FIXME: ceph flavor and kernel flavor are separate things
        'flavor': 'kernel_flavor',
        '<config_yaml>': 'base_yaml_paths',
        'filter': 'filter_in',
    }
    for (key, value) in args.items():
        # Translate --foo-bar to foo_bar
        key = key.lstrip('--').replace('-', '_')
        # Rename the key if necessary
        key = rename_args.get(key) or key
        if key == 'suite':
            value = value.replace('/', ':')
        elif key in ('limit', 'priority', 'num', 'newest'):
            value = int(value)
        elif key == 'subset' and value is not None:
            # take input string '2/3' and turn into (2, 3)
            value = tuple(map(int, value.split('/')))
        conf[key] = value
    return conf


def main(args):
    conf = process_args(args)
    if conf.verbose:
        teuthology.log.setLevel(logging.DEBUG)

    if not conf.machine_type or conf.machine_type == 'None':
        schedule_fail("Must specify a machine_type")
    elif 'multi' in conf.machine_type:
        schedule_fail("'multi' is not a valid machine_type. " +
                      "Maybe you want 'plana,mira,burnupi' or similar")

    if conf.email:
        config.results_email = conf.email
    if conf.archive_upload:
        config.archive_upload = conf.archive_upload
        log.info('Will upload archives to ' + conf.archive_upload)

    run = Run(conf)
    name = run.name
    run.prepare_and_schedule()
    if not conf.dry_run and conf.wait:
        return wait(name, config.max_job_time,
                    conf.archive_upload_url)


class WaitException(Exception):
    pass


def wait(name, max_job_time, upload_url):
    stale_job = max_job_time + Run.WAIT_MAX_JOB_TIME
    reporter = ResultsReporter()
    past_unfinished_jobs = []
    progress = time.time()
    log.info("waiting for the suite to complete")
    log.debug("the list of unfinished jobs will be displayed "
              "every " + str(Run.WAIT_PAUSE / 60) + " minutes")
    exit_code = 0
    while True:
        jobs = reporter.get_jobs(name, fields=['job_id', 'status'])
        unfinished_jobs = []
        for job in jobs:
            if job['status'] in UNFINISHED_STATUSES:
                unfinished_jobs.append(job)
            elif job['status'] != 'pass':
                exit_code = 1
        if len(unfinished_jobs) == 0:
            log.info("wait is done")
            break
        if (len(past_unfinished_jobs) == len(unfinished_jobs) and
                time.time() - progress > stale_job):
            raise WaitException(
                "no progress since " + str(config.max_job_time) +
                " + " + str(Run.WAIT_PAUSE) + " seconds")
        if len(past_unfinished_jobs) != len(unfinished_jobs):
            past_unfinished_jobs = unfinished_jobs
            progress = time.time()
        time.sleep(Run.WAIT_PAUSE)
        job_ids = [job['job_id'] for job in unfinished_jobs]
        log.debug('wait for jobs ' + str(job_ids))
    jobs = reporter.get_jobs(name, fields=['job_id', 'status',
                                           'description', 'log_href'])
    # dead, fail, pass : show fail/dead jobs first
    jobs = sorted(jobs, key=lambda j: j['status'])
    for job in jobs:
        if upload_url:
            url = os.path.join(upload_url, name, job['job_id'])
        else:
            url = job['log_href']
        log.info(job['status'] + " " + url + " " + job['description'])
    return exit_code
