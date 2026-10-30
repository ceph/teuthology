import gzip
import logging
import os
import re
import shutil

from datetime import datetime, timezone

import teuthology
from teuthology.contextutil import safe_while
from teuthology.util.time import parse_timestamp

log = logging.getLogger(__name__)


# If we see this in any directory, we do not prune it
PRESERVE_FILE = '.preserve'

# Scheduling timestamp that teuthology-suite puts in run names (TIMESTAMP_FMT),
# e.g. 'owner-2026-05-30_14:46:42-rados-main-distro-default-smithi'
RUN_NAME_TIMESTAMP_RE = re.compile(r'-(\d{4}-\d{2}-\d{2}_\d{2}:\d{2}:\d{2})-')


def main(args):
    """
    Main function; parses args and calls prune_archive()
    """
    verbose = args['--verbose']
    if verbose:
        teuthology.log.setLevel(logging.DEBUG)
    archive_dir = args['--archive']
    dry_run = args['--dry-run']
    pass_days = int(args['--pass'])
    fail_days = int(args['--fail'])
    remotes_days = int(args['--remotes'])
    compress_days = int(args['--compress'])

    prune_archive(
        archive_dir, pass_days, fail_days, remotes_days, compress_days, dry_run
    )


def prune_archive(
        archive_dir,
        pass_days,
        fail_days,
        remotes_days,
        compress_days,
        dry_run=False,
):
    """
    Walk through the archive_dir, calling the cleanup functions to process
    directories that might be old enough
    """
    min_days = min(filter(
        lambda n: n >= 0, [pass_days, fail_days, remotes_days]))
    # one clock reading for the whole pass, so every run is judged alike
    now = datetime.now(timezone.utc)
    log.debug("Archive {archive} has {count} children".format(
        archive=archive_dir, count=len(os.listdir(archive_dir))))
    # Use full paths
    children = [os.path.join(archive_dir, p) for p in listdir(archive_dir)]
    run_dirs = list()
    for child in children:
        # Ensure that the path is not a symlink, is a directory, and is old
        # enough to process
        if (not os.path.islink(child) and os.path.isdir(child) and
                is_older_than(run_schedule_time(child), min_days, now)):
            run_dirs.append(child)
    run_dirs.sort(key=lambda p: os.path.getctime(p), reverse=True)
    for run_dir in run_dirs:
        log.debug("Processing %s ..." % run_dir)
        maybe_remove_jobs(run_dir, pass_days, fail_days, now, dry_run)
        maybe_remove_remotes(run_dir, remotes_days, now, dry_run)
        maybe_compress_logs(run_dir, compress_days, now, dry_run)


def listdir(path):
    with safe_while(sleep=1, increment=1, tries=10) as proceed:
        while proceed():
            try:
                return os.listdir(path)
            except OSError:
                log.exception("Failed to list %s !" % path)


def should_preserve(dir_name):
    """
    Should the directory be preserved?

    :returns: True if the directory contains a file named '.preserve'; False
              otherwise
    """
    preserve_path = os.path.join(dir_name, PRESERVE_FILE)
    if os.path.isdir(dir_name) and os.path.exists(preserve_path):
        return True
    return False


def is_older_than(when, days, now):
    """
    :param when: A timezone-aware datetime
    :param now:  The timezone-aware datetime to measure from
    :returns: True if `when` is more than `days` days before `now`; always
              False for negative `days`
    """
    if days < 0:
        return False
    return (now - when).days > days


def run_schedule_time(run_dir):
    """
    :returns: When the run was scheduled, as a datetime: the timestamp in
              its name, or the directory's creation time if the name has
              none
    """
    match = RUN_NAME_TIMESTAMP_RE.search(os.path.basename(run_dir))
    if match:
        try:
            return parse_timestamp(match.group(1))
        except ValueError:
            pass
    return datetime.fromtimestamp(os.path.getctime(run_dir), timezone.utc)


def remove(path):
    """
    Attempt to recursively remove a directory. If an OSError is encountered,
    log it and continue.
    """
    try:
        shutil.rmtree(path)
    except OSError:
        log.exception("Failed to remove %s !" % path)


def maybe_remove_jobs(run_dir, pass_days, fail_days, now, dry_run=False):
    """
    Remove entire job log directories from a run old enough for its passed
    (or failed) jobs to go
    """
    scheduled = run_schedule_time(run_dir)
    remove_passed = is_older_than(scheduled, pass_days, now)
    remove_failed = is_older_than(scheduled, fail_days, now)
    if not (remove_passed or remove_failed):
        return
    contents = listdir(run_dir)
    if PRESERVE_FILE in contents:
        return
    for child in contents:
        job_path = os.path.join(run_dir, child)
        # Ensure the path isn't marked for preservation and that it is a
        # directory
        if should_preserve(job_path) or not os.path.isdir(job_path):
            continue
        # Is it a job dir?
        summary_path = os.path.join(job_path, 'summary.yaml')
        if not os.path.exists(summary_path):
            continue
        summary_lines = [line.strip() for line in
                         open(summary_path).readlines()]
        if 'success: true' in summary_lines:
            status = 'passed'
            days = pass_days
            remove_it = remove_passed
        elif 'success: false' in summary_lines:
            status = 'failed'
            days = fail_days
            remove_it = remove_failed
        else:
            continue
        if not remove_it:
            continue
        log.info("{job} is a {days}-day old {status} job; removing".format(
            job=job_path, days=days, status=status))
        if not dry_run:
            remove(job_path)


def maybe_remove_remotes(run_dir, days, now, dry_run=False):
    """
    Remove remote logs (not teuthology logs) from the job directories of a run
    that is old enough
    """
    if not is_older_than(run_schedule_time(run_dir), days, now):
        return
    contents = listdir(run_dir)
    subdirs = dict(
        remote='remote logs',
        data='mon data',
    )
    if PRESERVE_FILE in contents:
        return
    for child in contents:
        item = os.path.join(run_dir, child)
        # Ensure the path isn't marked for preservation and is a directory
        if should_preserve(item) or not os.path.isdir(item):
            continue
        for (subdir, description) in subdirs.items():
            _maybe_remove_subdir(item, subdir, days, description, dry_run)


def _maybe_remove_subdir(job_dir, subdir, days, description, dry_run=False):
    # Does the subdir exist?
    subdir_path = os.path.join(job_dir, subdir)
    if not os.path.isdir(subdir_path):
        return
    log.info("{job} is {days} days old; removing {desc}".format(
        job=job_dir,
        days=days,
        desc=description,
    ))
    if not dry_run:
        remove(subdir_path)


def maybe_compress_logs(run_dir, days, now, dry_run=False):
    if not is_older_than(run_schedule_time(run_dir), days, now):
        return
    contents = listdir(run_dir)
    if PRESERVE_FILE in contents:
        return
    for child in contents:
        item = os.path.join(run_dir, child)
        # Ensure the path isn't marked for preservation and is a directory
        if should_preserve(item) or not os.path.isdir(item):
            continue
        log_name = 'teuthology.log'
        log_path = os.path.join(item, log_name)
        if not os.path.exists(log_path):
            continue
        log.info("{job} is {days} days old; compressing {name}".format(
            job=item,
            days=days,
            name=log_name,
        ))
        if dry_run:
            continue
        zlog_path = log_path + '.gz'
        try:
            _compress(log_path, zlog_path)
        except Exception:
            log.exception("Failed to compress %s", log_path)
            os.remove(zlog_path)
        else:
            os.remove(log_path)


def _compress(in_path, out_path):
    """
    Compresses a file using gzip, preserving the original permissions, atime,
    and mtime.  Does not remove the original.
    """
    with open(in_path, 'rb') as src, gzip.open(out_path, 'wb') as dest:
        shutil.copyfileobj(src, dest)
    # only after close(): the gzip trailer write would reset the mtime
    shutil.copystat(in_path, out_path)
