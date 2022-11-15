"""
This task is used to integration test teuthology. Including this
task in your yaml config will execute pytest which finds any tests in
the current directory.  Each test that is discovered will be passed the
teuthology ctx and config args that each teuthology task usually gets.
This allows the tests to operate against the cluster.

An example::

    tasks
      - tests:

"""
import logging
import pathlib
import pexpect
import pytest

from teuthology.job_status import set_status


log = logging.getLogger(__name__)


@pytest.fixture
def ctx():
    return {}


@pytest.fixture
def config():
    return []


class TeuthologyContextPlugin(object):
    def __init__(self, ctx, config):
        self.ctx = ctx
        self.config = config
        self.failures = list()

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
        if report.outcome.lower() in ['passed', 'skipped']:
            if call.when == 'call':
                log.info(log_msg)
            else:
                log.info(f"{log_msg} {call.when=}")
        else:
            log_msg = f"{log_msg}:{call.when}"
            if call.excinfo:
                self.failures.append(f"{log_msg}: {call.excinfo.exconly}")
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


def run_cli(pytest_args):
    _, status = pexpect.run(
        " ".join(['py.test'] + pytest_args),
        cwd=str(pathlib.Path(__file__).parents[4]),
        withexitstatus=True,
        timeout=None,
    )
    return status, []

def run_py(pytest_args):
    context_plugin = TeuthologyContextPlugin(ctx, config)
    status = pytest.main(
        args=pytest_args,
        plugins=[context_plugin]
    )
    return status, context_plugin.failures


def task(ctx, config):
    """
    Use pytest to recurse through this directory, finding any tests
    and then executing them with the teuthology ctx and config args.
    Your tests must follow standard pytest conventions to be discovered.

    If config["mode"] == "cli", the py.test will be invoked as a subprocess.
    Otherwise, it will be run in the job's process.
    """
    mode = (config or dict()).get("mode", "py")
    pytest_args = ['-rA', '-v', './teuthology', './scripts']
    if len(ctx.cluster.remotes):
        pytest_args.append(__name__)
    try:
        if mode == "cli":
            status, failures = run_cli(pytest_args)
        else:
            status, failures = run_py(pytest_args)
    except Exception:
        log.exception("Saw non-test failure!")
        set_status(ctx.summary, "dead")
    else:
        if status == 0:
            log.info("OK. All tests passed!")
            set_status(ctx.summary, "pass")
        else:
            status_msg = str(status)
            if status in exit_codes:
                status_msg = f"{status_msg}: {exit_codes[status]}"
            log.error(f"FAIL (exit code {status_msg})")
            if failures:
                log.error(f"Failures: {failures}")
            set_status(ctx.summary, "fail")
