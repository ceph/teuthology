import argparse
import sys

import teuthology.dispatcher.supervisor


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Supervise and run a teuthology job; normally only run by the dispatcher",
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
        help="path in which to store the job's logfiles",
        required=True,
    )
    parser.add_argument(
        "--bin-path",
        type=str,
        help="teuthology bin path",
        required=True,
    )
    parser.add_argument(
        "--job-config",
        type=str,
        help="file descriptor of job's config file",
        required=True,
    )
    return parser.parse_args(argv)


def main():
    sys.exit(teuthology.dispatcher.supervisor.main(parse_args(sys.argv[1:])))


if __name__ == "__main__":
    main()
