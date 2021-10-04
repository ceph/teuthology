import argparse
"""
usage: teuthology-dispatcher --help
       teuthology-dispatcher --supervisor [-v] --bin-path BIN_PATH --job-config CONFIG --archive-dir DIR
       teuthology-dispatcher [-v] [--archive-dir DIR] --log-dir LOG_DIR --machine-type MACHINE_TYPE --queue-backend BACKEND

Start a dispatcher for the specified machine type. Grab jobs from a paddles/beanstalk
queue and run the teuthology tests they describe as subprocesses. The
subprocess invoked is a teuthology-dispatcher command run in supervisor
mode.

Supervisor mode: Supervise the job run described by its config. Reimage
target machines and invoke teuthology command. Unlock the target machines
at the end of the run.

standard arguments:
  -h, --help                     show this help message and exit
  -v, --verbose                  be more verbose
  -l, --log-dir LOG_DIR          path in which to store logs
  -a DIR, --archive-dir DIR      path to archive results in
  --machine-type MACHINE_TYPE    the machine type for the job
  --supervisor                   run dispatcher in job supervisor mode
  --bin-path BIN_PATH            teuthology bin path
  --job-config CONFIG            file descriptor of job's config file
  --exit-on-empty-queue          if the queue is empty, exit
  --queue-backend BACKEND        choose between paddles and beanstalk
"""

import docopt
import sys

import teuthology.dispatcher.supervisor

from .supervisor import parse_args as parse_supervisor_args


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Start a dispatcher for the specified tube. Grab jobs from a beanstalk queue and run the teuthology tests they describe as subprocesses. The subprocess invoked is teuthology-supervisor."
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="be more verbose",
    )
    parser.add_argument(
        "-a",
        "--archive-dir",
        type=str,
        help="path to archive results in",
    )
    parser.add_argument(
        "-t",
        "--tube",
        type=str,
        help="which beanstalk tube to read jobs from",
        required=True,
    )
    parser.add_argument(
        "-l",
        "--log-dir",
        type=str,
        help="path in which to store the dispatcher log",
        required=True,
    )
    parser.add_argument(
        "--exit-on-empty-queue",
        action="store_true",
        help="if the queue is empty, exit",
    )
    return parser.parse_args(argv)


def main():
    if "--supervisor" in sys.argv:
        # This is for transitional compatibility, so the old dispatcher can
        # invoke the new supervisor. Once old dispatchers are phased out,
        # this block can be as well.
        sys.argv.remove("--supervisor")
        sys.argv[0] = "teuthology-supervisor"
        sys.exit(teuthology.dispatcher.supervisor.main(
            parse_supervisor_args(sys.argv[1:])
        ))
    else:
        sys.exit(teuthology.dispatcher.main(parse_args(sys.argv[1:])))


if __name__ == "__main__":
    main()
