from mock import patch, MagicMock

from io import BytesIO
import os, io

from teuthology.orchestra import remote
from teuthology.util.scanner import UnitTestScanner, ValgrindScanner


class MockFile(io.StringIO):
    def close(self):
        pass


class TestUnitTestScanner(object):

    def setup_method(self):
        self.remote = remote.Remote(
            name='jdoe@xyzzy.example.com', ssh=MagicMock())
        self.test_values = {
            "xml_path": os.path.dirname(__file__) + "/files/test_unit_test.xml",
            "error_msg": "FAILURE: Test `test_set_bucket_tagging` of `s3tests_boto3.functional.test_s3`. \
Reason: 'NoSuchTagSetError' != 'NoSuchTagSet'.",
            "summary_data": [{'failed_testsuites': {'s3tests_boto3.functional.test_s3': 
                                [{'kind': 'failure', 'testcase': 'test_set_bucket_tagging', 
                                  'message': "'NoSuchTagSetError' != 'NoSuchTagSet'"}]}, 
                              'num_of_failures': 1, 
                              'file_path': f'{os.path.dirname(__file__)}/files/test_unit_test.xml'}],
            "yaml_data": r"""- failed_testsuites:
    s3tests_boto3.functional.test_s3:
    - kind: failure
      message: '''NoSuchTagSetError'' != ''NoSuchTagSet'''
      testcase: test_set_bucket_tagging
  file_path: {file_dir}/files/test_unit_test.xml
  num_of_failures: 1
""".format(file_dir=os.path.dirname(__file__))
        }

    @patch('teuthology.util.scanner.UnitTestScanner.write_summary')
    def test_scan_and_write(self, m_write_summary):
        xml_path = self.test_values["xml_path"]
        self.remote.ssh.exec_command.return_value = (None, BytesIO(xml_path.encode('utf-8')), None)
        m_open = MagicMock()
        m_open.return_value = open(xml_path, "rb")
        self.remote._sftp_open_file = m_open
        result = UnitTestScanner(remote=self.remote).scan_and_write(xml_path, "test_summary.yaml")
        assert result == "(total 1 failed) " + self.test_values["error_msg"]

    def test_parse(self):
        xml_content = b'<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="xyz" tests="1" \
errors="0" failures="1">\n<testcase classname="xyz" name="abc" time="0.059"><failure \
type="builtins.AssertionError" message="error_msg"></failure></testcase>\n</testsuite>'
        scanner = UnitTestScanner(self.remote)
        result = scanner._parse(xml_content)
        assert result == (
            'FAILURE: Test `abc` of `xyz`. Reason: error_msg.', 
            {'failed_testsuites': {'xyz': 
                [{'kind': 'failure','message': 'error_msg','testcase': 'abc'}]},
            'num_of_failures': 1
            }
        )
    
    def test_scan_file(self):
        xml_path = self.test_values["xml_path"]
        m_open = MagicMock()
        m_open.return_value = open(xml_path, "rb")
        self.remote._sftp_open_file = m_open
        scanner = UnitTestScanner(remote=self.remote)
        result = scanner.scan_file(xml_path)
        assert result == self.test_values["error_msg"]
        assert scanner.summary_data == self.test_values["summary_data"]

    def test_scan_all_files(self):
        xml_path = self.test_values["xml_path"]
        self.remote.ssh.exec_command.return_value = (None, BytesIO(xml_path.encode('utf-8')), None)
        m_open = MagicMock()
        m_open.return_value = open(xml_path, "rb")
        self.remote._sftp_open_file = m_open
        scanner = UnitTestScanner(remote=self.remote)
        result = scanner.scan_all_files(xml_path)
        assert result == [self.test_values["error_msg"]]
                          
    @patch('builtins.open')
    def test_write_summary(self, m_open):
        scanner = UnitTestScanner(self.remote)
        mock_yaml_file = MockFile()
        scanner.summary_data = self.test_values["summary_data"]
        m_open.return_value = mock_yaml_file
        scanner.write_summary("path/file.yaml")
        written_content = mock_yaml_file.getvalue()             
        assert written_content == self.test_values["yaml_data"]    


class TestValgrindScanner(object):

    def setup_method(self):
        self.remote = remote.Remote(
            name='jdoe@xyzzy.example.com', ssh=MagicMock())
        self.test_values = {
            "xml_path": os.path.dirname(__file__) + "/files/test_valgrind.xml",
            "error_msg": "valgrind error: Leak_DefinitelyLost\noperator new[]\
(unsigned long)\nceph::common::leak_some_memory()",
            "summary_data": [{'kind': 'Leak_DefinitelyLost', 'traceback': [{'file': 
                '/builddir/build/BUILD/valgrind-3.19.0/coregrind/m_replacemalloc/vg_replace_malloc.c', 
                'line': '640', 'function': 'operator new[](unsigned long)'}, 
                {'file': '/usr/src/debug/ceph-18.0.0-5567.g64a4fc94.el8.x86_64/src/common/ceph_context.cc', 
                 'line': '510', 'function': 'ceph::common::leak_some_memory()'}], 'file_path': 
                 f'{os.path.dirname(__file__)}/files/test_valgrind.xml'}],
            "yaml_data": r"""- file_path: {file_dir}/files/test_valgrind.xml
  kind: Leak_DefinitelyLost
  traceback:
  - file: /builddir/build/BUILD/valgrind-3.19.0/coregrind/m_replacemalloc/vg_replace_malloc.c
    function: operator new[](unsigned long)
    line: '640'
  - file: /usr/src/debug/ceph-18.0.0-5567.g64a4fc94.el8.x86_64/src/common/ceph_context.cc
    function: ceph::common::leak_some_memory()
    line: '510'
""".format(file_dir=os.path.dirname(__file__))
        }

    def test_parse_with_traceback(self):
        xml_content = b'''<?xml version="1.0"?>
<valgrindoutput>
<error>
  <kind>Leak_DefinitelyLost</kind>
  <stack>
    <frame>
      <fn>func()</fn>
      <dir>/dir</dir>
      <file>file1.ext</file>
      <line>640</line>
    </frame>
  </stack>
</error>
</valgrindoutput>
'''
        scanner = ValgrindScanner(self.remote)
        result = scanner._parse(xml_content)
        assert result == (
            'valgrind error: Leak_DefinitelyLost\nfunc()', 
            {'kind': 'Leak_DefinitelyLost', 'traceback': 
                [{'file': '/dir/file1.ext', 'line': '640', 'function': 'func()'}]
            }
        )

    def test_parse_without_trackback(self):
        xml_content = b'''<?xml version="1.0"?>
<valgrindoutput>
<error>
  <kind>Leak_DefinitelyLost</kind>
  <stack>
  </stack>
</error>
</valgrindoutput>
'''
        scanner = ValgrindScanner(self.remote)
        result = scanner._parse(xml_content)
        assert result == (
            'valgrind error: Leak_DefinitelyLost\n', 
            {'kind': 'Leak_DefinitelyLost', 'traceback': []}
        )
    
    def test_scan_file(self):
        xml_path = self.test_values["xml_path"]
        m_open = MagicMock()
        m_open.return_value = open(xml_path, "rb")
        self.remote._sftp_open_file = m_open
        scanner = ValgrindScanner(remote=self.remote)
        result = scanner.scan_file(xml_path)
        assert result == self.test_values["error_msg"]
        assert scanner.summary_data == self.test_values["summary_data"]

    def test_scan_all_files(self):
        xml_path = self.test_values["xml_path"]
        self.remote.ssh.exec_command.return_value = (None, BytesIO(xml_path.encode('utf-8')), None)
        m_open = MagicMock()
        m_open.return_value = open(xml_path, "rb")
        self.remote._sftp_open_file = m_open
        scanner = ValgrindScanner(remote=self.remote)
        result = scanner.scan_all_files(xml_path)
        assert result == [self.test_values["error_msg"]]
                          
    @patch('builtins.open')
    def test_write_summary(self, m_open):
        scanner = ValgrindScanner(self.remote)
        mock_yaml_file = MockFile()
        scanner.summary_data = self.test_values["summary_data"]
        m_open.return_value = mock_yaml_file
        scanner.write_summary("path/file.yaml")
        written_content = mock_yaml_file.getvalue()             
        assert written_content == self.test_values["yaml_data"]