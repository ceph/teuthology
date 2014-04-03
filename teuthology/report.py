import os
from os.path import getmtime
import yaml
import json
import re
import requests
import logging
import socket
from datetime import datetime

import teuthology
from .config import config
from .contextutil import safe_while


def init_logging():
    """
    Set up logging for the module

    :returns: a logger
    """
    # Don't need to see connection pool INFO messages
    logging.getLogger("requests.packages.urllib3.connectionpool").setLevel(
        logging.WARNING)

    log = logging.getLogger(__name__)
    return log


def main(args):
    run = args['--run']
    job = args['--job']
    dead = args['--dead']
    refresh = dead or args['--refresh']
    server = args['--server']
    if server:
        config.results_server = server
    if args['--verbose']:
        teuthology.log.setLevel(logging.DEBUG)

    archive_base = os.path.abspath(os.path.expanduser(args['--archive']))
    save = not args['--no-save']

    log = init_logging()
    reporter = ResultsReporter(archive_base, save=save, refresh=refresh,
                               log=log)
    if dead and not job:
        for run_name in run:
            reporter.report_run(run[0], dead=True)
    elif dead and len(run) == 1 and job:
        reporter.report_jobs(run[0], job, dead=True)
    elif len(run) == 1 and job:
        reporter.report_jobs(run[0], job)
    elif run and len(run) > 1:
        reporter.report_runs(run)
    elif run:
        reporter.report_run(run[0])
    elif args['--all-runs']:
        reporter.report_all_runs()


class ResultsSerializer(object):
    """
    This class exists to poke around in the archive directory doing things like
    assembling lists of test runs, lists of their jobs, and merging sets of job
    YAML files together to form JSON objects.
    """
    yamls = ('orig.config.yaml', 'config.yaml', 'info.yaml', 'summary.yaml')

    def __init__(self, archive_base, log=None):
        self.archive_base = archive_base
        self.log = log or init_logging()

    def job_info(self, run_name, job_id, pretty=False):
        """
        Given a run name and job id, merge the job's YAML files together.

        :param run_name: The name of the run.
        :param job_id:   The job's id.
        :returns:        A dict.
        """
        job_archive_dir = os.path.join(self.archive_base,
                                       run_name,
                                       job_id)
        job_info = {}
        for yaml_name in self.yamls:
            yaml_path = os.path.join(job_archive_dir, yaml_name)
            if not os.path.exists(yaml_path):
                continue
            with file(yaml_path) as yaml_file:
                partial_info = yaml.safe_load(yaml_file)
                if partial_info is not None:
                    job_info.update(partial_info)

        log_path = os.path.join(job_archive_dir, 'teuthology.log')
        if os.path.exists(log_path):
            mtime = int(os.path.getmtime(log_path))
            mtime_dt = datetime.fromtimestamp(mtime)
            job_info['updated'] = str(mtime_dt)

        if 'job_id' not in job_info:
            job_info['job_id'] = job_id

        return job_info

    def json_for_job(self, run_name, job_id, pretty=False):
        """
        Given a run name and job id, merge the job's YAML files together to
        create a JSON object.

        :param run_name: The name of the run.
        :param job_id:   The job's id.
        :returns:        A JSON object.
        """
        job_info = self.job_info(run_name, job_id, pretty)
        if pretty:
            job_json = json.dumps(job_info, sort_keys=True, indent=4)
        else:
            job_json = json.dumps(job_info)

        return job_json

    def jobs_for_run(self, run_name):
        """
        Given a run name, look on the filesystem for directories containing job
        information, and return a dict mapping job IDs to job directories.

        :param run_name: The name of the run.
        :returns:        A dict like: {'1': '/path/to/1', '2': 'path/to/2'}
        """
        archive_dir = os.path.join(self.archive_base, run_name)
        if not os.path.isdir(archive_dir):
            return {}
        jobs = {}
        for item in os.listdir(archive_dir):
            if not re.match('\d+$', item):
                continue
            job_id = item
            job_dir = os.path.join(archive_dir, job_id)
            if os.path.isdir(job_dir):
                jobs[job_id] = job_dir
        return jobs

    def running_jobs_for_run(self, run_name):
        """
        Like jobs_for_run(), but only returns jobs with no summary.yaml

        :param run_name: The name of the run.
        :returns:        A dict like: {'1': '/path/to/1', '2': 'path/to/2'}
        """
        jobs = self.jobs_for_run(run_name)
        for job_id in jobs.keys():
            if os.path.exists(os.path.join(jobs[job_id], 'summary.yaml')):
                jobs.pop(job_id)
        return jobs

    @property
    def all_runs(self):
        """
        Look in the base archive directory for all test runs. Return a list of
        their names.
        """
        archive_base = self.archive_base
        if not os.path.isdir(archive_base):
            return []
        runs = []
        for run_name in os.listdir(archive_base):
            if not os.path.isdir(os.path.join(archive_base, run_name)):
                continue
            runs.append(run_name)
        return runs


class ResultsReporter(object):
    last_run_file = 'last_successful_run'

    def __init__(self, archive_base, base_uri=None, save=False, refresh=False,
                 timeout=20, log=None):
        self.log = log or init_logging()
        self.archive_base = archive_base
        self.base_uri = base_uri or config.results_server
        if self.base_uri:
            self.base_uri = self.base_uri.rstrip('/')
        self.serializer = ResultsSerializer(archive_base, log=self.log)
        self.save_last_run = save
        self.refresh = refresh
        self.timeout = timeout

    def report_all_runs(self):
        """
        Report *all* runs in self.archive_dir to the results server.
        """
        all_runs = self.serializer.all_runs
        last_run = self.last_run
        if self.save_last_run and last_run and last_run in all_runs:
            next_index = all_runs.index(last_run) + 1
            runs = all_runs[next_index:]
        else:
            runs = all_runs
        return self.report_runs(runs)

    def report_runs(self, run_names):
        """
        Report several runs to the results server.

        :param run_names: The names of the runs.
        """
        num_runs = len(run_names)
        num_jobs = 0
        self.log.info("Posting %s runs", num_runs)
        for run in run_names:
            job_count = self.report_run(run)
            num_jobs += job_count
            if self.save_last_run:
                self.last_run = run
        del self.last_run
        self.log.info("Total: %s jobs in %s runs", num_jobs, len(run_names))

    def report_run(self, run_name, dead=False):
        """
        Report a single run to the results server.

        :param run_name: The name of the run.
        :returns:        The number of jobs reported.
        """
        jobs = self.serializer.jobs_for_run(run_name)
        self.log.info("{name} {jobs} jobs dead={dead}".format(
            name=run_name,
            jobs=len(jobs),
            dead=str(dead),
        ))
        if jobs:
            if not self.refresh:
                response = requests.head("{base}/runs/{name}/".format(
                    base=self.base_uri, name=run_name))
                if response.status_code == 200:
                    self.log.info("    already present; skipped")
                    return 0
            self.report_jobs(run_name, jobs.keys(), dead=dead)
        elif not jobs:
            self.log.debug("    no jobs; skipped")
        return len(jobs)

    def report_jobs(self, run_name, job_ids, dead=False):
        """
        Report several jobs to the results server.

        :param run_name: The name of the run.
        :param job_ids:  The jobs' ids
        """
        for job_id in job_ids:
            self.report_job(run_name, job_id, dead=dead)

    def report_job(self, run_name, job_id, job_info=None, dead=False):
        """
        Report a single job to the results server.

        :param run_name: The name of the run. The run must already exist.
        :param job_id:   The job's id
        :param job_info: The job's info dict. Optional - if not present, we
                         look at the archive.
        """
        if job_info is not None and not isinstance(job_info, dict):
            raise TypeError("job_info must be a dict")
        run_uri = "{base}/runs/{name}/jobs/".format(
            base=self.base_uri, name=run_name,)
        if job_info is None:
            job_info = self.serializer.job_info(run_name, job_id)
        if dead and job_info.get('success') is None:
            job_info['status'] = 'dead'
        job_json = json.dumps(job_info)
        headers = {'content-type': 'application/json'}
        response = requests.post(run_uri, data=job_json, headers=headers)

        if response.status_code == 200:
            return job_id

        if response.json:
            msg = response.json.get('message', '')
        else:
            msg = response.text

        if msg and msg.endswith('already exists'):
            job_uri = os.path.join(run_uri, job_id, '')
            response = requests.put(job_uri, data=job_json, headers=headers)
        elif msg:
            self.log.error(
                "POST to {uri} failed with status {status}: {msg}".format(
                    uri=run_uri,
                    status=response.status_code,
                    msg=msg,
                ))
        response.raise_for_status()

        return job_id

    @property
    def last_run(self):
        """
        The last run to be successfully reported.
        """
        if hasattr(self, '__last_run'):
            return self.__last_run
        elif os.path.exists(self.last_run_file):
            with file(self.last_run_file) as f:
                self.__last_run = f.read().strip()
            return self.__last_run

    @last_run.setter
    def last_run(self, run_name):
        self.__last_run = run_name
        with file(self.last_run_file, 'w') as f:
            f.write(run_name)

    @last_run.deleter
    def last_run(self):
        self.__last_run = None
        if os.path.exists(self.last_run_file):
            os.remove(self.last_run_file)


def push_job_info(run_name, job_id, job_info, base_uri=None):
    """
    Push a job's info (example: ctx.config) to the results server.

    :param run_name: The name of the run.
    :param job_id:   The job's id
    :param job_info: A dict containing the job's information.
    :param base_uri: The endpoint of the results server. If you leave it out
                     ResultsReporter will ask teuthology.config.
    """
    # We are using archive_base='' here because we KNOW the serializer isn't
    # needed for this codepath.
    reporter = ResultsReporter(archive_base='')
    reporter.report_job(run_name, job_id, job_info)


def try_push_job_info(job_config, extra_info=None):
    """
    Wrap push_job_info, gracefully doing nothing if:
        Anything inheriting from requests.exceptions.RequestException is raised
        A socket.error is raised
        config.results_server is not set
        config['job_id'] is not present or is None

    :param job_config: The ctx.config object to push
    :param extra_info: Optional second dict to push
    """
    log = init_logging()

    if not config.results_server:
        msg = "No results_server set in {yaml}; not attempting to push results"
        log.debug(msg.format(yaml=config.teuthology_yaml))
        return
    elif job_config.get('job_id') is None:
        log.warning('No job_id found; not reporting results')
        return

    run_name = job_config['name']
    job_id = job_config['job_id']

    if extra_info is not None:
        job_info = extra_info.copy()
        job_info.update(job_config)
    else:
        job_info = job_config

    with safe_while(_raise=False) as proceed:
        while proceed():
            try:
                log.info("Pushing job info to %s", config.results_server)
                push_job_info(run_name, job_id, job_info)
                return
            except (requests.exceptions.RequestException, socket.error):
                log.exception("Could not report results to %s",
                              config.results_server)
