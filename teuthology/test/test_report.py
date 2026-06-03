import json
from unittest.mock import Mock

import pytest
import yaml

from teuthology.test import fake_archive
from teuthology import report


@pytest.fixture
def archive(tmp_path):
    archive = fake_archive.FakeArchive(archive_base=str(tmp_path))
    yield archive
    archive.teardown()


@pytest.fixture(autouse=True)
def reporter(archive):
    archive.setup()
    return report.ResultsReporter(archive_base=archive.archive_base)


def test_all_runs_one_run(archive, reporter):
    run_name = "test_all_runs"
    yaml_path = "examples/3node_ceph.yaml"
    job_count = 3
    archive.create_fake_run(run_name, job_count, yaml_path)
    assert [run_name] == reporter.serializer.all_runs


def test_all_runs_three_runs(archive, reporter):
    run_count = 3
    runs = {}
    for i in range(run_count):
        run_name = "run #%s" % i
        yaml_path = "examples/3node_ceph.yaml"
        job_count = 3
        job_ids = archive.create_fake_run(
            run_name,
            job_count,
            yaml_path)
        runs[run_name] = job_ids
    assert sorted(runs.keys()) == sorted(reporter.serializer.all_runs)


def test_jobs_for_run(archive, reporter):
    run_name = "test_jobs_for_run"
    yaml_path = "examples/3node_ceph.yaml"
    job_count = 3
    jobs = archive.create_fake_run(run_name, job_count, yaml_path)
    job_ids = [str(job['job_id']) for job in jobs]

    got_jobs = reporter.serializer.jobs_for_run(run_name)
    assert sorted(job_ids) == sorted(got_jobs.keys())


def test_running_jobs_for_run(archive, reporter):
    run_name = "test_jobs_for_run"
    yaml_path = "examples/3node_ceph.yaml"
    job_count = 10
    num_hung = 3
    archive.create_fake_run(run_name, job_count, yaml_path,
                                 num_hung=num_hung)

    got_jobs = reporter.serializer.running_jobs_for_run(run_name)
    assert len(got_jobs) == num_hung


def test_json_for_job(archive, reporter):
    run_name = "test_json_for_job"
    yaml_path = "examples/3node_ceph.yaml"
    job_count = 1
    jobs = archive.create_fake_run(run_name, job_count, yaml_path)
    job = jobs[0]

    with open(yaml_path) as yaml_file:
        obj_from_yaml = yaml.safe_load(yaml_file)
    full_obj = obj_from_yaml.copy()
    full_obj.update(job['info'])
    full_obj.update(job['summary'])

    out_json = reporter.serializer.json_for_job(
        run_name, str(job['job_id']))
    out_obj = json.loads(out_json)
    assert full_obj == out_obj


def test_normalize_tags():
    assert report.normalize_tags('Foo, bar') == ['foo', 'bar']
    assert report.normalize_tags(['Squid', 'Reef']) == ['squid', 'reef']
    assert report.normalize_tags('') == []
    assert report.normalize_tags(None) == []


def test_create_run_posts_to_paddles_runs():
    reporter = report.ResultsReporter(archive_base='/tmp')
    reporter.base_uri = 'http://paddles:8080'
    reporter.session = Mock()
    ok = Mock(status_code=200)
    reporter.session.post.return_value = ok

    reporter.create_run('my-run', 'tracker-74166')

    reporter.session.post.assert_called_once_with(
        'http://paddles:8080/runs/',
        json={'name': 'my-run', 'tags': ['tracker-74166']},
    )


def test_create_run_puts_when_run_already_exists():
    reporter = report.ResultsReporter(archive_base='/tmp')
    reporter.base_uri = 'http://paddles:8080'
    reporter.session = Mock()
    exists = Mock(status_code=400)
    exists.json.return_value = {
        'message': 'run with name my-run already exists',
    }
    reporter.session.post.return_value = exists
    reporter.session.put.return_value = Mock(status_code=200)

    reporter.create_run('my-run', ['squid'])

    reporter.session.put.assert_called_once_with(
        'http://paddles:8080/runs/my-run/',
        json={'tags': ['squid']},
    )


