import docopt
import sys

import teuthology.testplan
from teuthology.suite import override_arg_defaults as defaults
from teuthology.config import config

doc = """
usage: teuthology-testplan --help
       teuthology-testplan run [-v | -vv] [options] <testplan>
       teuthology-testplan show [-v | -vv] [options] <testplan>
       teuthology-testplan list [-v | -vv] [options]
       teuthology-testplan validate [-v | -vv] [options] <testplan>...

Schedule and inspect testplans. A testplan is a YAML file listing suite runs,
each with its own subset, filters, limit and distro. Plans don't name any
branch, sha1 or machine type, so the same plan can be run against any build,
in any lab. See docs/testplans.rst for the file format.

<testplan> is either a file path, or a plan name such as 'pr-smoke', which is
looked up as <suite_relpath>/testplans/<name>.yaml in the suite repo.

Commands:
  run                         Schedule one run per entry in the plan. The plan
                              is checked first, and nothing is scheduled if
                              anything is wrong with it or if the total number
                              of jobs is too high.
  show                        Show each run with defaults applied, and how
                              many jobs it would schedule.
  list                        List the testplans in the suite repo.
  validate                    Check testplan files. Without --suite-dir, only
                              the files themselves are checked; with it, the
                              suites they name are checked too. Does not use
                              the network.

Miscellaneous arguments:
  -h, --help                  Show this help message and exit
  -v, --verbose               Be more verbose
  --dry-run                   (run) Do a dry run; do not schedule anything.
  -y, --non-interactive       (run) Do not ask questions.
  --wait                      (run) Block until all runs are finished.

Validation arguments:
  --jobs                      (validate) Also build each run's jobs and report
                              how many there are. Requires --suite-dir.
  --strict                    (validate) Treat runs with no jobs as errors
                              rather than warnings. Implies --jobs.

Build and suite arguments:
  -c <ceph>, --ceph <ceph>    The ceph branch to run against
                              [default: {default_ceph_branch}]
  -S <sha1>, --sha1 <sha1>    The ceph sha1 to run against (overrides -c)
  -k <kernel>, --kernel <kernel>
                              The kernel branch to run against,
                              use 'none' to bypass kernel task.
                              [default: distro]
  -f <flavor>, --flavor <flavor>
                              The ceph packages shaman flavor to run with:
                              ('default', 'crimson', 'notcmalloc', 'jaeger')
                              [default: default]
  -t <branch>, --teuthology-branch <branch>
                              The teuthology branch to run against. Chosen
                              the same way as by teuthology-suite.
  --ceph-repo <ceph_repo>     Query this repository for Ceph branch and SHA1
                              values [default: {default_ceph_repo}]
  --suite-repo <suite_repo>   Use tasks, suite and testplan definitions in this
                              repository [default: {default_suite_repo}]
  --suite-relpath <suite_relpath>
                              Look for tasks, suites and testplans in this
                              subdirectory of the suite repo.
                              [default: qa]
  --suite-branch <suite_branch>
                              Use this suite branch instead of the ceph branch
  --suite-sha1 <suite_sha1>   The suite sha1 to use (overrides --suite-branch)
  --suite-dir <suite_dir>     Use this directory as-is for suites and
                              testplans, e.g. a ceph.git checkout.
  --validate-sha1 <bool>      Validate that git SHA1s passed to -S exist.
                              [default: true]
  --kdb <bool>                Enable/disable kdb in kernel [default: true]

Lab arguments:
  -m <type>, --machine-type <type>
                              Machine type [default: {default_machine_type}]
  --arch <arch>               Override architecture defaults, for example,
                              aarch64, armv7l, x86_64. Normally the arch is
                              determined from --machine-type.

Scheduler arguments:
  -p <priority>, --priority <priority>
                              Job priority (lower is sooner) [default: 1000]
  --force-priority            Skip the priority check.
  --job-threshold <threshold>
                              Do not schedule anything if the plan's total
                              number of jobs exceeds <threshold>. Use 0 to
                              allow any number [default: {default_job_threshold}].
  --owner <owner>             Job owner
  -b <backend>, --queue-backend <backend>
                              Scheduler queue backend name
  -e <email>, --email <email>
                              When tests finish or time out, send an email
                              here.
  --expire <datetime>         Do not execute jobs if they have not completed
                              by this time. Valid formats include ISO 8601,
                              and relative offsets like '90s', '30m', '1h',
                              '3d', or '1w'
  --archive-upload RSYNC_DEST Rsync destination to upload archives.
  --archive-upload-url URL    Public facing URL where archives are uploaded.
  --throttle SLEEP            When scheduling, wait SLEEP seconds between jobs.
""".format(
    default_machine_type=config.default_machine_type,
    default_ceph_repo=defaults('--ceph-repo',
                               config.get_ceph_git_url()),
    default_suite_repo=defaults('--suite-repo',
                                config.get_ceph_qa_suite_git_url()),
    default_ceph_branch=defaults('--ceph-branch', 'main'),
    default_job_threshold=config.job_threshold,
)


def main(argv=sys.argv[1:]):
    args = docopt.docopt(doc, argv=argv)
    return teuthology.testplan.main(args)
