import pytest

from mock import patch, Mock, mock_open

from teuthology import ls


class TestLs(object):
    """ Tests for teuthology.ls """

    @patch('os.path.isdir')
    @patch('os.listdir')
    def test_get_jobs(self, m_listdir, m_isdir):
        m_listdir.return_value = ["1", "a", "3"]
        m_isdir.return_value = True
        results = ls.get_jobs("some/archive/dir")
        assert results == ["1", "3"]

    @patch("yaml.safe_load_all")
    @patch("teuthology.ls.open")
    @patch("teuthology.ls.get_jobs")
    def test_ls(self, m_get_jobs, m_file, m_safe_load_all):
        m_get_jobs.return_value = ["1", "2"]
        m_safe_load_all.return_value = [{"failure_reason": "reasons"}]
        ls.ls("some/archive/div", True)

    @patch("teuthology.ls.open")
    @patch("teuthology.ls.get_jobs")
    def test_ls_ioerror(self, m_get_jobs, m_file):
        m_get_jobs.return_value = ["1", "2"]
        m_file.side_effect = IOError()
        with pytest.raises(IOError):
            ls.ls("some/archive/dir", True)

    @patch("teuthology.ls.open", mock_open(read_data='... some/archive/dir'))
    @patch("os.popen")
    @patch("os.path.isdir")
    @patch("os.path.isfile")
    def test_print_debug_info(self, m_isfile, m_isdir, m_popen):
        m_isfile.return_value = True
        m_isdir.return_value = True
        m_popen.return_value = Mock()
        ls.print_debug_info("the_job", "job/dir", "some/archive/dir")
