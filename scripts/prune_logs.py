import argparse

import teuthology.config
import teuthology.prune

def main():
    parser = argparse.ArgumentParser(
        description='Prune old logfiles from the archive',
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Be more verbose'
    )
    parser.add_argument(
        '-a', '--archive',
        default=teuthology.config.config.archive_base,
        help=f'The base archive directory (default: {teuthology.config.config.archive_base})'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Don't actually delete anything; just log what would be deleted"
    )
    parser.add_argument(
        '-p', '--pass',
        type=int,
        default=14,
        metavar='DAYS',
        dest='pass_days',
        help='Remove all logs for jobs which passed and are older than DAYS. Negative values will skip this operation. (default: 14)'
    )
    parser.add_argument(
        '-f', '--fail',
        type=int,
        default=-1,
        metavar='DAYS',
        dest='fail_days',
        help='Like --pass, but for failed jobs. (default: -1)'
    )
    parser.add_argument(
        '-r', '--remotes',
        type=int,
        default=60,
        metavar='DAYS',
        help="Remove the 'remote' subdir of jobs older than DAYS. Negative values will skip this operation. (default: 60)"
    )
    parser.add_argument(
        '-z', '--compress',
        type=int,
        default=30,
        metavar='DAYS',
        help='Compress (using gzip) any teuthology.log files older than DAYS. Negative values will skip this operation. (default: 30)'
    )
    args = parser.parse_args()
    teuthology.prune.main(args.__dict__)
