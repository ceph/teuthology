import argparse
import sys

import teuthology.testplan
from teuthology.suite import override_arg_defaults as defaults
from teuthology.config import config

DESCRIPTION = """
Schedule and inspect testplans. A testplan is a YAML file listing suite runs,
each with its own subset, filters, limit and distro. Plans don't name any
branch, sha1 or machine type, so the same plan can be run against any build,
in any lab. See docs/testplans.rst for the file format.

TESTPLAN is either a file path, or a plan name such as 'pr-smoke', which is
looked up as <suite-relpath>/testplans/<name>.yaml in the suite repo.
"""


def add_common_args(parser):
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Be more verbose",
    )


def add_suite_dir_args(parser):
    group = parser.add_argument_group("Suite arguments")
    group.add_argument(
        "--suite-relpath",
        default="qa",
        help="Look for tasks, suites and testplans in this subdirectory of "
             "the suite repo (default: %(default)s)",
    )
    group.add_argument(
        "--suite-dir",
        help="Use this directory as-is for suites and testplans, e.g. a "
             "ceph.git checkout.",
    )
    return group


def add_suite_args(parser):
    group = add_suite_dir_args(parser)
    group.add_argument(
        "-c", "--ceph",
        default=defaults('--ceph-branch', 'main'),
        help="The ceph branch to run against (default: %(default)s)",
    )
    group.add_argument(
        "-S", "--sha1",
        help="The ceph sha1 to run against (overrides -c)",
    )
    group.add_argument(
        "--ceph-repo",
        default=defaults('--ceph-repo', config.get_ceph_git_url()),
        help="Query this repository for Ceph branch and SHA1 values "
             "(default: %(default)s)",
    )
    group.add_argument(
        "--suite-repo",
        default=defaults('--suite-repo', config.get_ceph_qa_suite_git_url()),
        help="Use tasks, suite and testplan definitions in this repository "
             "(default: %(default)s)",
    )
    group.add_argument(
        "--suite-branch",
        help="Use this suite branch instead of the ceph branch",
    )
    group.add_argument(
        "--suite-sha1",
        help="The suite sha1 to use (overrides --suite-branch). Defaults "
             "to the -S sha1 when the suite repo is the ceph repo",
    )
    group.add_argument(
        "--validate-sha1",
        metavar="BOOL",
        default="true",
        help="Validate that git SHA1s passed to -S exist "
             "(default: %(default)s)",
    )


def add_run_args(parser):
    group = parser.add_argument_group("Run arguments")
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Do a dry run; do not schedule anything.",
    )
    group.add_argument(
        "-y", "--non-interactive",
        action="store_true",
        help="Do not ask questions.",
    )
    group.add_argument(
        "--wait",
        action="store_true",
        help="Block until all runs are finished.",
    )

    group = parser.add_argument_group("Build arguments")
    group.add_argument(
        "-k", "--kernel",
        default="distro",
        help="The kernel branch to run against, use 'none' to bypass kernel "
             "task. (default: %(default)s)",
    )
    group.add_argument(
        "-f", "--flavor",
        default="default",
        help="The ceph packages shaman flavor to run with: ('default', "
             "'crimson', 'notcmalloc', 'jaeger') (default: %(default)s)",
    )
    group.add_argument(
        "-t", "--teuthology-branch",
        metavar="BRANCH",
        help="The teuthology branch to run against. Chosen the same way as "
             "by teuthology-suite.",
    )
    group.add_argument(
        "--kdb",
        metavar="BOOL",
        default="true",
        help="Enable/disable kdb in kernel (default: %(default)s)",
    )

    group = parser.add_argument_group("Lab arguments")
    group.add_argument(
        "-m", "--machine-type",
        metavar="TYPE",
        default=config.default_machine_type,
        help="Machine type (default: %(default)s)",
    )
    group.add_argument(
        "--arch",
        help="Override architecture defaults, for example, aarch64, armv7l, "
             "x86_64. Normally the arch is determined from --machine-type.",
    )

    group = parser.add_argument_group("Scheduler arguments")
    group.add_argument(
        "-p", "--priority",
        type=int,
        default=1000,
        help="Job priority (lower is sooner) (default: %(default)s)",
    )
    group.add_argument(
        "--force-priority",
        action="store_true",
        help="Skip the priority check.",
    )
    group.add_argument(
        "--job-threshold",
        metavar="THRESHOLD",
        type=int,
        default=config.job_threshold,
        help="Do not schedule anything if the plan's total number of jobs "
             "exceeds THRESHOLD. Use 0 to allow any number "
             "(default: %(default)s)",
    )
    group.add_argument(
        "--owner",
        help="Job owner",
    )
    group.add_argument(
        "-b", "--queue-backend",
        metavar="BACKEND",
        help="Scheduler queue backend name",
    )
    group.add_argument(
        "-e", "--email",
        help="When tests finish or time out, send an email here.",
    )
    group.add_argument(
        "--expire",
        metavar="DATETIME",
        help="Do not execute jobs if they have not completed by this time. "
             "Valid formats include ISO 8601, and relative offsets like "
             "'90s', '30m', '1h', '3d', or '1w'",
    )
    group.add_argument(
        "--archive-upload",
        metavar="RSYNC_DEST",
        help="Rsync destination to upload archives.",
    )
    group.add_argument(
        "--archive-upload-url",
        metavar="URL",
        help="Public facing URL where archives are uploaded.",
    )
    group.add_argument(
        "--throttle",
        metavar="SLEEP",
        help="When scheduling, wait SLEEP seconds between jobs.",
    )


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="teuthology-testplan",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(
        dest="command", metavar="COMMAND", required=True)

    run = commands.add_parser(
        "run",
        help="Schedule one run per entry in the plan.",
        description="Schedule one run per entry in the plan. The plan is "
                    "checked first, and nothing is scheduled if anything is "
                    "wrong with it or if the total number of jobs is too "
                    "high.",
    )
    add_common_args(run)
    add_suite_args(run)
    add_run_args(run)
    run.add_argument("testplan", metavar="TESTPLAN")

    show = commands.add_parser(
        "show",
        help="Show each run with defaults applied, and how many jobs it "
             "would schedule.",
    )
    add_common_args(show)
    add_suite_args(show)
    show.add_argument("testplan", metavar="TESTPLAN")

    list_ = commands.add_parser(
        "list",
        help="List the testplans in the suite repo.",
    )
    add_common_args(list_)
    add_suite_args(list_)

    validate = commands.add_parser(
        "validate",
        help="Check testplan files.",
        description="Check testplan files. Without --suite-dir, only the "
                    "files themselves are checked; with it, the suites they "
                    "name are checked too. Does not use the network.",
    )
    add_common_args(validate)
    add_suite_dir_args(validate)
    group = validate.add_argument_group("Validation arguments")
    group.add_argument(
        "--jobs",
        action="store_true",
        help="Also build each run's jobs and report how many there are. "
             "Requires --suite-dir.",
    )
    group.add_argument(
        "--strict",
        action="store_true",
        help="Treat runs with no jobs as errors rather than warnings. "
             "Implies --jobs.",
    )
    validate.add_argument("testplan", metavar="TESTPLAN", nargs="+")

    return parser.parse_args(argv)


def main(argv=None):
    return teuthology.testplan.main(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
