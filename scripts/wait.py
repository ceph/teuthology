import argparse
import sys

import logging

import teuthology
import teuthology.suite
from teuthology.config import config

def _build_parser():
    parser = argparse.ArgumentParser(
        description='Wait until run is finished. Returns exit code 0 on success, otherwise 1.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Be more verbose'
    )
    parser.add_argument(
        '-r', '--run',
        required=True,
        metavar='<name>',
        help='Run name to watch'
    )
    return parser


def parse_args(argv=None):
    return _build_parser().parse_args(argv)


def main(argv=sys.argv[1:]):
    args = parse_args(argv)
    if args.verbose:
        teuthology.log.setLevel(logging.DEBUG)
    return teuthology.suite.wait(args.run, config.max_job_time, None)

