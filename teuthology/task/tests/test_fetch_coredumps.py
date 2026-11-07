from teuthology.task.internal import fetch_binaries_for_coredumps, get_dump_program
from unittest.mock import patch, Mock
import gzip
import os
import pytest

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
        self.uncompressed_execfn_differs = self.MockPopen(
            "ELF 64-bit LSB core file,"\
            " x86-64, version 1 (SYSV), SVR4-style, from 'ceph-osd -f --cluster ceph',"\
            " real uid: 1194, effective uid: 1194, real gid: 1194,"\
            " effective gid: 1194, execfn: '/usr/bin/crimson-osd', platform: 'x86_64'"
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

    # execfn differs from 'from' field (which may be spoofed)
    @patch('teuthology.task.internal.subprocess.Popen')
    @patch('teuthology.task.internal.os')
    def test_execfn_preferred_over_from(self, m_os, m_subproc_popen):
        m_subproc_popen.side_effect = [
                self.uncompressed_execfn_differs,
                Exception("We shouldn't be hitting this!")
            ]
        m_os.path.join.return_value = self.core_dump_path
        m_os.path.sep = '/'
        m_os.path.isabs.return_value = True
        m_os.path.isdir.return_value = True
        m_os.path.dirname.return_value = self.core_dump_path
        m_os.path.exists.return_value = True
        m_os.listdir.return_value = [self.core_dump_path]
        self.the_function(None, self.m_remote)
        assert self.m_remote._sftp_get_file.called

    def teardown(self):
        os.remove(self.core_dump_path)


class TestGetDumpProgram(object):
    def test_execfn_preferred_over_from(self):
        file_info = (
            "ELF 64-bit LSB core file, x86-64, version 1 (SYSV), SVR4-style,"
            " from 'ceph-osd -f --cluster ceph',"
            " execfn: '/usr/bin/crimson-osd', platform: 'x86_64'"
        )
        assert get_dump_program(file_info) == '/usr/bin/crimson-osd'

    def test_from_field_when_no_execfn(self):
        file_info = (
            "ELF 64-bit LSB core file, x86-64, version 1 (SYSV), SVR4-style,"
            " from 'radosgw --rgw-socket-path /tmp/sock'"
        )
        assert get_dump_program(file_info) == 'radosgw'

    def test_raises_on_unparseable(self):
        with pytest.raises(ValueError):
            get_dump_program("ASCII text")