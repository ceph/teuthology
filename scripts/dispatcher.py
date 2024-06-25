import argparse
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
