import argparse
import sys

import teuthology.lock
import teuthology.lock.cli

desc = """
Update any hostkeys that have changed. You can list specific machines to run
on, or use -a to check all of them automatically.
"""


def main():
    parser = argparse.ArgumentParser(
        description=desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'machines',
        nargs='*',
        metavar='MACHINES',
        help='hosts to check for updated keys'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Be more verbose'
    )
    parser.add_argument(
        '-t', '--targets',
        metavar='<targets>',
        help='Input yaml containing targets to check'
    )
    parser.add_argument(
        '-a', '--all',
        action='store_true',
        help='Update hostkeys of all machines in the db'
    )
    args = parser.parse_args()
    status = teuthology.lock.cli.updatekeys(args.__dict__)
    sys.exit(status)
