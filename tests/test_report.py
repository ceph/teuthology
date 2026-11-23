import json
import pytest
import yaml
from mock import Mock, patch

from tests import fake_archive
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


def test_register_run_posts_tags_list():
    reporter = report.ResultsReporter(base_uri='http://paddles.example')
    reporter.session = Mock()
    reporter.session.post.return_value = Mock(status_code=200)
    reporter.register_run(
        'user-2025-01-01_00:00:00-smoke-main-testing-basic-plana',
        ['v20.2.2.rc1-fs', 'smoke'],
    )
    reporter.session.post.assert_called_once()
    uri = reporter.session.post.call_args[0][0]
    body = json.loads(reporter.session.post.call_args[1]['data'])
    assert uri == 'http://paddles.example/runs/'
    assert body == {
        'name': 'user-2025-01-01_00:00:00-smoke-main-testing-basic-plana',
        'tags': ['v20.2.2.rc1-fs', 'smoke'],
    }


def test_register_run_puts_tags_when_run_exists():
    reporter = report.ResultsReporter(base_uri='http://paddles.example')
    reporter.session = Mock()
    reporter.session.post.return_value = Mock(
        status_code=400,
        json=Mock(return_value={
            'message': 'run with name foo already exists',
        }),
        text='',
    )
    reporter.session.put.return_value = Mock(status_code=200)
    reporter.register_run('foo', ['release-qa'])
    reporter.session.put.assert_called_once()
    body = json.loads(reporter.session.put.call_args[1]['data'])
    assert body == {'tags': ['release-qa']}


@patch('teuthology.report.config')
def test_try_register_run_skips_without_server(mock_config):
    mock_config.results_server = None
    reporter = report.ResultsReporter()
    reporter.register_run = Mock()
    with patch('teuthology.report.ResultsReporter', return_value=reporter):
        report.try_register_run('foo', tags=['bar'])
    reporter.register_run.assert_not_called()


@patch('teuthology.report.config')
def test_try_register_run_calls_register(mock_config):
    mock_config.results_server = 'http://paddles'
    reporter = report.ResultsReporter(base_uri='http://paddles')
    reporter.register_run = Mock()
    with patch('teuthology.report.ResultsReporter', return_value=reporter):
        report.try_register_run('foo', tags=['bar'])
    reporter.register_run.assert_called_once_with('foo', ['bar'])


