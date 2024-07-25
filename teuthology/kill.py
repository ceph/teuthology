#!/usr/bin/python
import os
import sys
import yaml
import psutil
import subprocess
import logging
import getpass

from typing import Union

import teuthology.exporter

from teuthology import beanstalk
from teuthology import report
from teuthology.config import config
from teuthology.lock import ops as lock_ops

log = logging.getLogger(__name__)


def main(args):
    run_name = args['--run']
    job = args['--job']
    jobspec = args['--jobspec']
    archive_base = args['--archive']
    owner = args['--owner']
    machine_type = args['--machine-type']
    preserve_queue = args['--preserve-queue']

    if jobspec:
        split_spec = jobspec.split('/')
        run_name = split_spec[0]
        job = [split_spec[1]]

    if job:
        for job_id in job:
            kill_job(run_name, job_id, archive_base, owner)
    else:
        kill_run(run_name, archive_base, owner, machine_type,
                 preserve_queue=preserve_queue)


def kill_run(run_name, archive_base=None, owner=None, machine_type=None,
             preserve_queue=False):
    run_info = {}
    serializer = report.ResultsSerializer(archive_base)
    if archive_base:
        run_archive_dir = os.path.join(archive_base, run_name)
        if os.path.isdir(run_archive_dir):
            run_info = find_run_info(serializer, run_name)
            if 'machine_type' in run_info:
                machine_type = run_info['machine_type']
                owner = run_info['owner']
            else:
                log.warning("The run info does not have machine type: %s" % run_info)
                log.warning("Run archive used: %s" % run_archive_dir)
                log.info("Using machine type '%s' and owner '%s'" % (machine_type, owner))
        elif machine_type is None:
            # no jobs found in archive and no machine type specified,
            # so we try paddles to see if there is anything scheduled
            run_info = report.ResultsReporter().get_run(run_name)
            machine_type = run_info.get('machine_type', None)
            if machine_type:
                log.info(f"Using machine type '{machine_type}' received from paddles.")
            else:
                raise RuntimeError(f"Cannot find machine type for the run {run_name}; " +
                                    "you must also pass --machine-type")

    if not preserve_queue:
        remove_beanstalk_jobs(run_name, machine_type)
        remove_paddles_jobs(run_name)
    if kill_processes(run_name, run_info.get('pids')):
        return
    if owner is not None:
        targets = find_targets(run_name)
        names = list(targets.keys())
        lock_ops.unlock_safe(names, owner, run_name)
    report.try_mark_run_dead(run_name)


def kill_job(run_name, job_id, archive_base=None, owner=None, skip_unlock=False):
    serializer = report.ResultsSerializer(archive_base)
    job_info = serializer.job_info(run_name, job_id)
    # If we can't read the filesystem, job_info will be nearly empty. Ask paddles:
    if 'name' not in job_info:
        job_info = report.ResultsReporter().get_jobs(run_name, job_id)
    if not owner:
        if 'owner' not in job_info:
            raise RuntimeError(
                "I could not figure out the owner of the requested job. "
                "Please pass --owner <owner>.")
        owner = job_info['owner']
    if kill_processes(run_name, [job_info.get('pid')]):
        return
    report.try_push_job_info(job_info, dict(status="dead"))
    if 'machine_type' in job_info:
        teuthology.exporter.JobResults().record(
            machine_type=job_info["machine_type"],
            status=job_info.get("status", "dead")
        )
    else:
        log.warn(f"Job {job_id} has no machine_type; cannot report via Prometheus")
    if not skip_unlock:
        targets = find_targets(run_name, job_id)
        lock_ops.unlock_safe(list(targets.keys()), owner, run_name, job_id)


def find_run_info(serializer, run_name):
    log.info("Assembling run information...")
    run_info_fields = [
        'machine_type',
        'owner',
    ]

    pids = []
    run_info = {}
    job_info = {}
    job_num = 0
    jobs = serializer.jobs_for_run(run_name)
    job_total = len(jobs)
    for (job_id, job_dir) in jobs.items():
        if not os.path.isdir(job_dir):
            continue
        job_num += 1
        beanstalk.print_progress(job_num, job_total, 'Reading Job: ')
        job_info = serializer.job_info(run_name, job_id, simple=True)
        for key in job_info.keys():
            if key in run_info_fields and key not in run_info:
                run_info[key] = job_info[key]
        if 'pid' in job_info:
            pids.append(job_info['pid'])
    run_info['pids'] = pids
    return run_info


def remove_paddles_jobs(run_name):
    jobs = report.ResultsReporter().get_jobs(run_name, fields=['status'])
    job_ids = [job['job_id'] for job in jobs if job['status'] == 'queued']
    if job_ids:
        log.info("Deleting jobs from paddles: %s", str(job_ids))
        report.try_delete_jobs(run_name, job_ids)


def remove_beanstalk_jobs(run_name, tube_name):
    qhost = config.queue_host
    qport = config.queue_port
    if qhost is None or qport is None:
        raise RuntimeError(
            'Beanstalk queue information not found in {conf_path}'.format(
                conf_path=config.yaml_path))
    log.info("Checking Beanstalk Queue...")
    beanstalk_conn = beanstalk.connect()
    real_tube_name = beanstalk.watch_tube(beanstalk_conn, tube_name)

    curjobs = beanstalk_conn.stats_tube(real_tube_name)['current-jobs-ready']
    if curjobs != 0:
        x = 1
        while x != curjobs:
            x += 1
            job = beanstalk_conn.reserve(timeout=20)
            if job is None:
                continue
            job_config = yaml.safe_load(job.body)
            if run_name == job_config['name']:
                job_id = job.stats()['id']
                msg = "Deleting job from queue. ID: " + \
                    "{id} Name: {name} Desc: {desc}".format(
                        id=str(job_id),
                        name=job_config['name'],
                        desc=job_config['description'],
                    )
                log.info(msg)
                job.delete()
    else:
        print("No jobs in Beanstalk Queue")
    beanstalk_conn.close()


def kill_processes(run_name, pids=None):
    if pids:
        to_kill = set(pids).intersection(psutil.pids())
    else:
        to_kill = find_pids(run_name)

    pids_need_sudo = set()
    for pid in set(to_kill):
        if not process_matches_run(pid, run_name):
            to_kill.remove(pid)
        elif psutil.Process(int(pid)).username() != getpass.getuser():
            pids_need_sudo.add(pid)

    survivors = []
    if len(to_kill) == 0:
        log.info("No teuthology processes running")
    else:
        log.info("Killing Pids: " + str(to_kill))
        sudo_works = False
        if pids_need_sudo:
            sudo_works = subprocess.Popen(['sudo', '-n', '-l']).wait() == 0
            if not sudo_works:
                log.debug("Passwordless sudo not configured; not using sudo")
        for pid in to_kill:
            use_sudo = pid in pids_need_sudo and sudo_works
            args = ['kill', str(pid)]
            # Don't attempt to use sudo if it's not necessary
            if use_sudo:
                args = ['sudo', '-n'] + args
            try:
                subprocess.check_call(args)
            except subprocess.CalledProcessError:
                survivors.append(pid)
    if survivors:
        log.error(f"Failed to kill PIDs: {survivors}")
    return survivors


def process_matches_run(pid, run_name):
    try:
        p = psutil.Process(pid)
        cmd = p.cmdline()
        if run_name in cmd and sys.argv[0] not in cmd:
            return True
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied:
        pass
    return False


def find_pids(run_name):
    run_pids = []
    for pid in psutil.pids():
        if process_matches_run(pid, run_name):
            run_pids.append(pid)
    return run_pids

def find_targets(run_name: str, job_id: Union[str, int, None] = None) -> dict:
    if job_id is not None:
        job_info = report.ResultsReporter().get_jobs(run_name, str(job_id))
        return job_info.get("targets") or dict()
    result = dict()
    run_info = report.ResultsReporter().get_jobs(run_name)
    for job_info in run_info:
        if job_info.get("status") not in ("running", "waiting"):
            continue
        result.update(job_info.get("targets") or dict())
    return result
