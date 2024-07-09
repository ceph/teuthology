from unittest.mock import patch

from teuthology.kill import find_targets


class TestFindTargets(object):
    """ Tests for teuthology.kill.find_targets """

    @patch('teuthology.kill.report.ResultsReporter.get_jobs')
    def test_missing_run_find_targets(self, m_get_jobs):
        m_get_jobs.return_value = [] 
        run_targets = find_targets("run-name")
        assert run_targets == {}
    
    @patch('teuthology.kill.report.ResultsReporter.get_jobs')
    def test_missing_job_find_targets(self, m_get_jobs):
        m_get_jobs.return_value = {} 
        job_targets = find_targets("run-name", "3")
        assert job_targets == {}

    @patch('teuthology.kill.report.ResultsReporter.get_jobs')
    def test_missing_run_targets_find_targets(self, m_get_jobs):
        m_get_jobs.return_value = [{"targets": None, "status": "waiting"}] 
        run_targets = find_targets("run-name")
        assert run_targets == {}
    
    @patch('teuthology.kill.report.ResultsReporter.get_jobs')
    def test_missing_job_targets_find_targets(self, m_get_jobs):
        m_get_jobs.return_value = {"targets": None} 
        job_targets = find_targets("run-name", "3")
        assert job_targets == {}

    @patch('teuthology.kill.report.ResultsReporter.get_jobs')
    def test_run_find_targets(self, m_get_jobs):
        m_get_jobs.return_value = [{"targets": {"node1": ""}, "status": "running"}]
        run_targets = find_targets("run-name")
        assert run_targets == {"node1": ""}
        m_get_jobs.return_value = [{"targets": {"node1": ""}}]
        run_targets = find_targets("run-name")
        assert run_targets == {}

    @patch('teuthology.kill.report.ResultsReporter.get_jobs')
    def test_job_find_targets(self, m_get_jobs):
        m_get_jobs.return_value = {"targets": {"node1": ""}}
        job_targets = find_targets("run-name", "3")
        assert job_targets == {"node1": ""}
