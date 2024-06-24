import argparse
import sys

import teuthology.dispatcher


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
    sys.exit(teuthology.dispatcher.main(parse_args(sys.argv[1:])))


if __name__ == "__main__":
    main()
