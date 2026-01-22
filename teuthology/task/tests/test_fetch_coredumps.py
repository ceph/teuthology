from teuthology.task.internal import fetch_binaries_for_coredumps
from teuthology.task.internal import get_backtraces_from_coredumps
from unittest.mock import patch, Mock
import gzip
import os

class TestFetchCoreDumps(object):
    class MockDecode(object):
        def __init__(self, ret):
            self.ret = ret
            pass

        def decode(self):
            return self.ret

    class MockPopen(object):
        def __init__(self, ret):
            self.ret = ret

        def communicate(self, input=None):
            return [TestFetchCoreDumps.MockDecode(self.ret)]

    class MockCompletedProcess(object):
        def __init__(self, ret):
            self.ret = ret

        @property
        def stdout(self):
            return self.ret

    class MockGdb(object):
        def __init__(self, ret):
            self.ret = ret

        def run(self, *args, **kwargs):
            return TestFetchCoreDumps.MockCompletedProcess(self.ret)

    class TestGetBacktracesFromCoreDumps(object):
        @patch('teuthology.task.internal.subprocess.run')
        def test_get_backtraces_from_coredumps(self, mock_run):
            mock_run.return_value = TestFetchCoreDumps.MockCompletedProcess(
                "Backtrace line 1\nBacktrace line 2\nBacktrace line 3\n"
            )
            backtraces = get_backtraces_from_coredumps(coredump_path="core_dump_path", dump_path="binary_path", 
                                                       dump_program="ceph_test_rados_api_io", dump="core_dump")
            expected_backtraces = [
                "Backtrace line 1",
                "Backtrace line 2",
                "Backtrace line 3"
            ]
            assert backtraces == expected_backtraces

    def setup_method(self):
        self.the_function = fetch_binaries_for_coredumps
        with gzip.open('file.gz', 'wb') as f:
            f.write(b'Hello world!')
        self.core_dump_path = "file.gz"
        self.m_remote = Mock()
        self.uncompressed_correct = self.MockPopen(
            "ELF 64-bit LSB core file,"\
            " x86-64, version 1 (SYSV), SVR4-style, from 'ceph_test_rados_api_io',"\
            " real uid: 1194, effective uid: 1194, real gid: 1194,"\
            " effective gid: 1194, execfn: '/usr/bin/ceph_test_rados_api_io', platform: 'x86_64'"
        )
        self.uncompressed_incorrect = self.MockPopen("ASCII text")
        self.compressed_correct = self.MockPopen(
            "gzip compressed data, was "\
            "'correct.format.core', last modified: Wed Jun 29"\
            " 19:55:29 2022, from Unix, original size modulo 2^32 3167080"
        )

        self.compressed_incorrect = self.MockPopen(
            "gzip compressed data, was "\
            "'incorrect.format.core', last modified: Wed Jun 29"\
            " 19:56:56 2022, from Unix, original size modulo 2^32 11"
        )

        # Centos 9 coredumps are zstd compressed:
        self.zstd_compressed_correct = self.MockPopen(
            "Zstandard compressed data"\
            "'correct.format.core', last modified: Wed Jun 29"\
            " 19:55:29 2022, from Unix, original size modulo 2^32 3167080"
        )

        self.zstd_compressed_incorrect = self.MockPopen(
            "Zstandard compressed data"\
            "'incorrect.format.core', last modified: Wed Jun 29"\
            " 19:56:56 2022, from Unix, original size modulo 2^32 11"
        )


    # Core is not compressed and file is in the correct format
    @patch('teuthology.task.internal.subprocess.Popen')
    @patch('teuthology.task.internal.os')
    def test_uncompressed_correct_format(self, m_os, m_subproc_popen):
        m_subproc_popen.side_effect = [
                self.uncompressed_correct,
                Exception("We shouldn't be hitting this!")
            ]
        m_os.path.join.return_value = self.core_dump_path
        m_os.path.sep = self.core_dump_path
        m_os.path.isdir.return_value = True
        m_os.path.dirname.return_value = self.core_dump_path
        m_os.path.exists.return_value = True
        m_os.listdir.return_value = [self.core_dump_path]
        self.the_function(None, self.m_remote)
        assert self.m_remote.get_file.called

    # Core is not compressed and file is in the wrong format
    @patch('teuthology.task.internal.subprocess.Popen')
    @patch('teuthology.task.internal.os')
    def test_uncompressed_incorrect_format(self, m_os, m_subproc_popen):
        m_subproc_popen.side_effect = [
                self.uncompressed_incorrect,
                Exception("We shouldn't be hitting this!")
            ]
        m_os.path.join.return_value = self.core_dump_path
        m_os.path.sep = self.core_dump_path
        m_os.path.isdir.return_value = True
        m_os.path.dirname.return_value = self.core_dump_path
        m_os.path.exists.return_value = True
        m_os.listdir.return_value = [self.core_dump_path]
        self.the_function(None, self.m_remote)
        assert self.m_remote.get_file.called == False

    # Core is compressed and file is in the correct format
    @patch('teuthology.task.internal.subprocess.Popen')
    @patch('teuthology.task.internal.os')
    def test_compressed_correct_format(self, m_os, m_subproc_popen):
        m_subproc_popen.side_effect = [
                self.compressed_correct,
                self.uncompressed_correct
            ]
        m_os.path.join.return_value = self.core_dump_path
        m_os.path.sep = self.core_dump_path
        m_os.path.isdir.return_value = True
        m_os.path.dirname.return_value = self.core_dump_path
        m_os.path.exists.return_value = True
        m_os.listdir.return_value = [self.core_dump_path]
        self.the_function(None, self.m_remote)
        assert self.m_remote.get_file.called

    # Core is compressed and file is in the wrong format
    @patch('teuthology.task.internal.subprocess.Popen')
    @patch('teuthology.task.internal.os')
    def test_compressed_incorrect_format(self, m_os, m_subproc_popen):
        m_subproc_popen.side_effect = [
                self.compressed_incorrect,
                self.uncompressed_incorrect
            ]
        m_os.path.join.return_value = self.core_dump_path
        m_os.path.sep = self.core_dump_path
        m_os.path.isdir.return_value = True
        m_os.path.dirname.return_value = self.core_dump_path
        m_os.path.exists.return_value = True
        m_os.listdir.return_value = [self.core_dump_path]
        self.the_function(None, self.m_remote)
        assert self.m_remote.get_file.called == False

    # Core is zstd-compressed and file is in the correct format
    @patch('teuthology.task.internal.subprocess.Popen')
    @patch('teuthology.task.internal.os')
    def test_zstd_compressed_correct_format(self, m_os, m_subproc_popen):
        m_subproc_popen.side_effect = [
                self.zstd_compressed_correct,
                self.uncompressed_correct
            ]
        m_os.path.join.return_value = self.core_dump_path
        m_os.path.sep = self.core_dump_path
        m_os.path.isdir.return_value = True
        m_os.path.dirname.return_value = self.core_dump_path
        m_os.path.exists.return_value = True
        m_os.listdir.return_value = [self.core_dump_path]
        self.the_function(None, self.m_remote)
        assert self.m_remote.get_file.called

    # Core is compressed and file is in the wrong format
    @patch('teuthology.task.internal.subprocess.Popen')
    @patch('teuthology.task.internal.os')
    def test_zstd_compressed_incorrect_format(self, m_os, m_subproc_popen):
        m_subproc_popen.side_effect = [
                self.zstd_compressed_incorrect,
                self.uncompressed_incorrect
            ]
        m_os.path.join.return_value = self.core_dump_path
        m_os.path.sep = self.core_dump_path
        m_os.path.isdir.return_value = True
        m_os.path.dirname.return_value = self.core_dump_path
        m_os.path.exists.return_value = True
        m_os.listdir.return_value = [self.core_dump_path]
        self.the_function(None, self.m_remote)
        assert self.m_remote.get_file.called == False

    def teardown(self):
        os.remove(self.core_dump_path)
