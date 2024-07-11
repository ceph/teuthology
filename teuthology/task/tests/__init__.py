"""
This task runs teuthology's unit tests and integration tests.
It can run in one of two modes: "py" or "cli". The latter executes py.test in a
separate process, whereas the former invokes it in the teuthology job's python
process.
If the running job has remotes available to it, it will attempt to run integration tests.
Note that this requires running in "py" mode - the default.

An example::

    tasks
      - tests:
"""
import logging
import os
import pathlib
import pexpect
import pytest

from teuthology.job_status import set_status
from teuthology.task import Task
from teuthology.util.loggerfile import LoggerFile


log = logging.getLogger(__name__)


class TeuthologyContextPlugin(object):
    def __init__(self, ctx, config):
        self.ctx = ctx
        self.config = config
        self.failures = list()
        self.stats = dict()

    # this is pytest hook for generating tests with custom parameters
    def pytest_generate_tests(self, metafunc):
        # pass the teuthology ctx and config to each test method
        if "ctx" in metafunc.fixturenames and \
                "config" in metafunc.fixturenames:
            metafunc.parametrize(["ctx", "config"], [(self.ctx, self.config),])

    # log the outcome of each test
    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo):
        outcome = yield
        report = outcome.get_result()
        test_path = item.location[0]
        line_no = item.location[1]
        test_name = item.location[2]
        name = f"{test_path}:{line_no}:{test_name}"
        log_msg = f"{report.outcome.upper()} {name}"
        outcome_str = report.outcome.lower()
        self.stats.setdefault(outcome_str, 0)
        self.stats[outcome_str] += 1
        if outcome_str in ['passed', 'skipped']:
            if call.when == 'call':
                log.info(log_msg)
            else:
                log.info(f"----- {name} {call.when} -----")
        else:
            log_msg = f"{log_msg}:{call.when}"
            if call.excinfo:
                self.failures.append(name)
                log_msg = f"{log_msg}: {call.excinfo.getrepr()}"
            else:
                self.failures.append(log_msg)
            log.error(log_msg)

        return


# https://docs.pytest.org/en/stable/reference/exit-codes.html
exit_codes = {
    0: "All tests were collected and passed successfully",
    1: "Tests were collected and run but some of the tests failed",
    2: "Test execution was interrupted by the user",
    3: "Internal error happened while executing tests",
    4: "pytest command line usage error",
    5: "No tests were collected",
}


class Tests(Task):
    """
    Use pytest to recurse through this directory, finding any tests
    and then executing them with the teuthology ctx and config args.
    Your tests must follow standard pytest conventions to be discovered.

    If config["mode"] == "py", (the default), it will be run in the job's process.
    If config["mode"] == "cli" py.test will be invoked as a subprocess.
    """
    base_args = ['-v', '--color=no']

    def setup(self):
        super().setup()
        mode = self.config.get("mode", "py")
        assert mode in ["py", "cli"], "mode must either be 'py' or 'cli'"
        if mode == "cli":
            # integration tests need ctx from this process, so we need to invoke
            # pytest via python to be able to pass them
            assert len(self.cluster.remotes) == 0, \
                "Tests requiring remote nodes conflicts with CLI mode"
        self.mode = mode
        self.stats = dict()
        self.orig_curdir = os.curdir

    def begin(self):
        super().begin()
        try:
            if self.mode == "py":
                self.status, self.failures = self.run_py()
            else:
                self.status, self.failures = self.run_cli()
        except Exception as e:
            log.exception("Saw non-test failure!")
            self.ctx.summary['failure_reason'] = str(e)
            set_status(self.ctx.summary, "dead")

    def end(self):
        if os.curdir != self.orig_curdir:
            os.chdir(self.orig_curdir)
        if self.stats:
            log.info(f"Stats: {self.stats}")
        if self.status == 0:
            log.info("OK. All tests passed!")
            set_status(self.ctx.summary, "pass")
        else:
            status_msg = str(self.status)
            if self.status in exit_codes:
                status_msg = f"{status_msg}: {exit_codes[self.status]}"
            log.error(f"FAIL (exit code {status_msg})")
            if self.failures:
                msg = f"{len(self.failures)} Failures: {self.failures}"
                self.ctx.summary['failure_reason'] = msg
                log.error(msg)
            set_status(self.ctx.summary, "fail")
        super().end()

    def run_cli(self):
        pytest_args = self.base_args + ['./teuthology/test', './scripts']
        if len(self.cluster.remotes):
            pytest_args.append('./teuthology/task/tests')
        self.log.info(f"pytest args: {pytest_args}")
        cwd = str(pathlib.Path(__file__).parents[3])
        log.info(f"pytest cwd: {cwd}")
        _, status = pexpect.run(
            "py.test " + " ".join(pytest_args),
            cwd=cwd,
            withexitstatus=True,
            timeout=None,
            logfile=LoggerFile(self.log, logging.INFO),
        )
        return status, []

    def run_py(self):
        pytest_args = self.base_args + ['--pyargs', 'teuthology', 'scripts']
        if len(self.cluster.remotes):
            pytest_args.append(__name__)
        self.log.info(f"pytest args: {pytest_args}")
        context_plugin = TeuthologyContextPlugin(self.ctx, self.config)
        # the cwd needs to change so that FakeArchive can find files in this repo
        os.chdir(str(pathlib.Path(__file__).parents[3]))
        status = pytest.main(
            args=pytest_args,
            plugins=[context_plugin],
        )
        self.stats = context_plugin.stats
        return status, context_plugin.failures

task = Tests
