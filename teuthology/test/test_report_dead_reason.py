from unittest.mock import patch, MagicMock

import teuthology.report as report


@patch('teuthology.report.ResultsReporter')
def test_try_mark_run_dead_includes_reason(mock_reporter_cls):
    # Set up a fake reporter with serializer.job_info and report_job
    mock_reporter = MagicMock()
    mock_reporter_cls.return_value = mock_reporter

    # Simulate one job returned by get_jobs
    mock_reporter.get_jobs.return_value = [
        {'job_id': '1', 'status': 'running'}
    ]

    # serializer.job_info should return a dict representing archived job info
    mock_reporter.serializer.job_info.return_value = {
        'job_id': '1',
        'machine_type': 'smithi',
    }

    # Call the function under test
    report.try_mark_run_dead('fake-run', reason='killed by user')

    # Ensure report_job was called with job_info that contains failure_reason
    assert mock_reporter.report_job.called
    called_args, called_kwargs = mock_reporter.report_job.call_args
    # call signature: report_job(run_name, job_id, job_info=...)
    assert called_args[0] == 'fake-run'
    assert called_args[1] == '1'

    job_info = called_kwargs.get('job_info') if 'job_info' in called_kwargs else called_args[2]
    assert job_info['status'] == 'dead'
    assert job_info['failure_reason'] == 'killed by user'
