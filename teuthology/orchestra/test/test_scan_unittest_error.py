import os
from unittest.mock import patch
from teuthology.orchestra import run

class TestScanUnittestError(object):

    def setup(self):
        self.remote_process = run.RemoteProcess(None, None, hostname="hostname")
        self.the_function = self.remote_process._scan_unittest_error

    @patch('teuthology.orchestra.run.RemoteProcess._open_file_path_from_handler')
    def test_s3_nose_test_failure(self, m_open_file_path):
        m_open_file_path.return_value = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "teuth_log/s3_failure_teuth.log"
        )
        assert self.the_function() == ("ERROR: test suite for <module " 
                                       "'s3tests_boto3.functional' "
                                       "from '/home/ubuntu/cephtest/"
                                       "s3-tests/s3tests_boto3/functional/"
                                       "__init__.py'>")

    @patch('teuthology.orchestra.run.RemoteProcess._open_file_path_from_handler')
    def test_rbd_gtest_failure(self, m_open_file_path):
        m_open_file_path.return_value = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "teuth_log/gtest_failure_teuth.log"
        )
        assert self.the_function() == "[  FAILED  ] TestLibRBD.TestEncryptionLUKS2 (12236 ms)"
