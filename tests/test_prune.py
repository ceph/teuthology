import gzip
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from teuthology import prune
from teuthology.util.time import TIMESTAMP_FMT

DAY = 60 * 60 * 24
RUN_STAMP = '2026-05-30_14:46:42'
RUN_NAME = 'owner-%s-rados-main-distro-default-smithi' % RUN_STAMP
RUN_TIME = datetime.strptime(RUN_STAMP, TIMESTAMP_FMT).replace(
    tzinfo=timezone.utc)
NOW = datetime.now(timezone.utc)


def run_name(age_days):
    stamp = datetime.fromtimestamp(time.time() - age_days * DAY,
                                   timezone.utc).strftime(TIMESTAMP_FMT)
    return 'owner-%s-rados-main-distro-default-smithi' % stamp


def make_job(run_dir, job_id, success=None, remote=True, log=True):
    """
    Create a fake job dir. Every mtime is "now", so nothing here can be
    pruned by accident of modification times.
    """
    job_dir = run_dir / str(job_id)
    job_dir.mkdir()
    if remote:
        (job_dir / 'remote').mkdir()
        (job_dir / 'remote' / 'ceph-osd.0.log').write_text('osd log')
    if success is not None:
        (job_dir / 'summary.yaml').write_text(
            'success: %s\n' % ('true' if success else 'false'))
    if log:
        (job_dir / 'teuthology.log').write_text('log line\n' * 100)
    return job_dir


@pytest.fixture
def old_run(tmp_path):
    path = tmp_path / RUN_NAME
    path.mkdir()
    return path


@pytest.fixture
def new_run(tmp_path):
    path = tmp_path / run_name(10)
    path.mkdir()
    return path


def ctime(path):
    return datetime.fromtimestamp(os.path.getctime(str(path)), timezone.utc)


class TestRunScheduleTime:
    def test_parses_run_name_as_utc(self, old_run):
        assert prune.run_schedule_time(str(old_run)) == RUN_TIME

    def test_name_without_timestamp_uses_ctime(self, tmp_path):
        run = tmp_path / 'no-timestamp-here'
        run.mkdir()
        assert prune.run_schedule_time(str(run)) == ctime(run)

    def test_bad_timestamp_uses_ctime(self, tmp_path):
        run = tmp_path / 'owner-2026-99-99_14:46:42-rados'
        run.mkdir()
        assert prune.run_schedule_time(str(run)) == ctime(run)

    def test_mtime_is_ignored(self, old_run):
        now = time.time()
        os.utime(old_run, (now, now))
        assert prune.run_schedule_time(str(old_run)) == RUN_TIME


class TestIsOlderThan:
    def test_days_boundary(self):
        assert prune.is_older_than(NOW - timedelta(days=31), 30, NOW)
        assert not prune.is_older_than(
            NOW - timedelta(days=30, hours=12), 30, NOW)

    def test_negative_days_disables(self):
        assert not prune.is_older_than(RUN_TIME, -1, NOW)

    def test_measures_from_the_given_now(self):
        later = NOW + timedelta(days=365)
        assert prune.is_older_than(NOW - timedelta(days=1), 30, later)


class TestPruneSteps:
    def test_remotes_removed_from_old_run(self, old_run):
        job = make_job(old_run, 1, success=False)
        hung = make_job(old_run, 2)
        prune.maybe_remove_remotes(str(old_run), 90, NOW)
        assert not (job / 'remote').exists()
        assert not (hung / 'remote').exists()
        assert (job / 'teuthology.log').exists()

    def test_remotes_kept_in_new_run(self, new_run):
        job = make_job(new_run, 1, success=False)
        prune.maybe_remove_remotes(str(new_run), 90, NOW)
        assert (job / 'remote').exists()

    def test_remotes_dry_run(self, old_run):
        job = make_job(old_run, 1, success=False)
        prune.maybe_remove_remotes(str(old_run), 90, NOW, dry_run=True)
        assert (job / 'remote').exists()

    def test_compress_old_run_only(self, old_run, new_run):
        old = make_job(old_run, 1, success=False)
        new = make_job(new_run, 2, success=False)
        prune.maybe_compress_logs(str(old_run), 60, NOW)
        prune.maybe_compress_logs(str(new_run), 60, NOW)
        assert not (old / 'teuthology.log').exists()
        with gzip.open(old / 'teuthology.log.gz') as f:
            assert f.read().startswith(b'log line')
        assert (new / 'teuthology.log').exists()

    def test_compress_keeps_log_mtime(self, old_run):
        job = make_job(old_run, 1)
        then = time.time() - 100 * DAY
        os.utime(job / 'teuthology.log', (then, then))
        prune._compress(str(job / 'teuthology.log'),
                        str(job / 'teuthology.log.gz'))
        assert os.path.getmtime(job / 'teuthology.log.gz') == pytest.approx(
            then, abs=1)

    def test_passed_jobs_removed_failed_kept(self, old_run, new_run):
        passed = make_job(old_run, 1, success=True)
        failed = make_job(old_run, 2, success=False)
        recent = make_job(new_run, 3, success=True)
        prune.maybe_remove_jobs(str(old_run), 30, 365, NOW)
        prune.maybe_remove_jobs(str(new_run), 30, 365, NOW)
        assert not passed.exists()
        assert failed.exists()
        assert recent.exists()

    def test_young_run_jobs_not_listed(self, new_run, monkeypatch):
        make_job(new_run, 1, success=True)
        monkeypatch.setattr(prune, 'listdir', lambda path: pytest.fail(
            'listed a run too young to prune'))
        prune.maybe_remove_jobs(str(new_run), 30, 365, NOW)
        prune.maybe_remove_remotes(str(new_run), 90, NOW)
        prune.maybe_compress_logs(str(new_run), 60, NOW)

    def test_preserve_file_respected(self, old_run):
        job = make_job(old_run, 1, success=True)
        (job / prune.PRESERVE_FILE).write_text('')
        prune.maybe_remove_jobs(str(old_run), 30, -1, NOW)
        prune.maybe_remove_remotes(str(old_run), 90, NOW)
        assert (job / 'remote').exists()

    def test_prune_archive_gate_ignores_run_mtime(self, tmp_path):
        run = tmp_path / RUN_NAME
        run.mkdir()
        job = make_job(run, 1, success=False)
        # removing a sibling job bumps the run dir; it must still be visited
        now = time.time()
        os.utime(run, (now, now))
        prune.prune_archive(str(tmp_path), pass_days=30, fail_days=-1,
                            remotes_days=90, compress_days=60)
        assert not (job / 'remote').exists()
        assert (job / 'teuthology.log.gz').exists()
