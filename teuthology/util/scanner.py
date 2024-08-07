import logging
import yaml
from typing import Optional, Tuple
from collections import defaultdict
from lxml import etree

log = logging.getLogger(__name__)


class Scanner():
    def __init__(self, remote=None) -> None:
        self.summary_data = []
        self.remote = remote

    def _parse(self, file_content) -> Tuple[str, dict]:
        """
        This parses file_content and returns:
        :returns: a message string 
        :returns: data dictionary with additional info

        Just an abstract method in Scanner class, 
        to be defined in inherited classes. 
        """
        raise NotImplementedError
    
    def scan_file(self, path: str) -> Optional[str]:
        if not path:
            return None
        try:
            file = self.remote._sftp_open_file(path, 'r')
            file_content = file.read()
            txt, data = self._parse(file_content)
            if data:
                data["file_path"] = path
                self.summary_data += [data]
            file.close()
            return txt
        except Exception as exc:
            log.error(str(exc))

    def scan_all_files(self, path_regex: str) -> [str]:
        """
        Scans all files matching path_regex
        and collect additional data in self.summary_data 

        :param path_regex: Regex string to find all the files which have to be scanned. 
                           Example: /path/to/dir/*.xml
        """
        (_, stdout, _) = self.remote.ssh.exec_command(f'ls -d {path_regex}', timeout=200)
        
        files = stdout.read().decode().split('\n')
        
        extracted_txts = []
        for fpath in files:
            txt = self.scan_file(fpath)
            if txt:
                extracted_txts += [txt]
        return extracted_txts
    
    def write_summary(self, yaml_path: str) -> None:
        """
        Create yaml file locally 
        with self.summary_data.
        """
        if self.summary_data and yaml_path:
            with open(yaml_path, 'a') as f:
                yaml.safe_dump(self.summary_data, f, default_flow_style=False)
        else:
            log.info("summary_data or yaml_file is empty!")


class UnitTestScanner(Scanner):
    def __init__(self, remote=None) -> None:
        super().__init__(remote)

    def _parse(self, file_content: str) -> Tuple[Optional[str], Optional[dict]]:
        xml_tree = etree.fromstring(file_content)

        failed_testcases = xml_tree.xpath('.//failure/.. | .//error/..')
        if len(failed_testcases) == 0:
            return None, None

        exception_txt = ""
        error_data = defaultdict(list)
        for testcase in failed_testcases:
            testcase_name = testcase.get("name", "test-name")
            testcase_suitename = testcase.get("classname", "suite-name")
            for child in testcase:
                if child.tag in ['failure', 'error']:
                    fault_kind = child.tag
                    reason = child.get('message', 'No message found in xml output, check logs.')
                    short_reason = (reason[:200].strip() + '...') if len(reason) > 200 else reason.strip()
                    error_data[testcase_suitename] += [{
                            "kind": fault_kind, 
                            "testcase": testcase_name,
                            "message": reason,
                        }]
                    if not exception_txt:
                        exception_txt = f'{fault_kind.upper()}: Test `{testcase_name}` of `{testcase_suitename}`. Reason: {short_reason}.'
        
        return exception_txt, { "failed_testsuites": dict(error_data), "num_of_failures": len(failed_testcases) }

    @property
    def num_of_total_failures(self):
        total_failed_testcases = 0
        if self.summary_data:
            for file_data in self.summary_data:
                failed_tests = file_data.get("num_of_failures", 0)
                total_failed_testcases += failed_tests
        return total_failed_testcases

    def scan_and_write(self, path_regex: str, summary_path: str) -> Optional[str]:
        """
        Scan all files matching 'path_regex'
        and write summary in 'summary_path'.
        """
        try:
            errors = self.scan_all_files(path_regex)
            self.write_summary(summary_path)
            if errors:
                count = self.num_of_total_failures
                return f"(total {count} failed) " + errors[0]
        except Exception as scanner_exc:
            log.error(str(scanner_exc))


class ValgrindScanner(Scanner):
    def __init__(self, remote=None) -> None:
        super().__init__(remote)

    def _parse(self, file_content: str) -> Tuple[Optional[str], Optional[dict]]:
        xml_tree = etree.fromstring(file_content)
        if xml_tree is None:
            return None, None
        
        error_tree = xml_tree.find('error')
        if error_tree is None:
            return None, None
        
        error_data = {
            "kind": error_tree.findtext("kind"),
            "traceback": [],
        }
        for frame in error_tree.xpath("stack/frame"):
            if len(error_data["traceback"]) >= 5:
                break
            curr_frame = {
                "file": f"{frame.findtext('dir', '')}/{frame.findtext('file', '')}",
                "line": frame.findtext("line", ''),
                "function": frame.findtext("fn", ''),
            }
            error_data["traceback"].append(curr_frame)

        traceback_functions = "\n".join(
                frame.get("function", "N/A") 
                for frame in error_data["traceback"][:3]
            )
        exception_text = f"valgrind error: {error_data['kind']}\n{traceback_functions}"
        return exception_text, error_data
