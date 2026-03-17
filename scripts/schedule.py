import argparse

import teuthology.misc
import teuthology.schedule
import sys

def main(argv=sys.argv[1:]):
    parser = argparse.ArgumentParser(
        description='Schedule ceph integration tests',
    )
    parser.add_argument(
        'conf_file',
        nargs='*',
        metavar='<conf_file>',
        help='Config file to read. "-" indicates read stdin.'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Be more verbose'
    )
    parser.add_argument(
        '-b', '--queue-backend',
        default='beanstalk',
        metavar='<backend>',
        help="Queue backend name, use prefix '@' to append job config to the given file path as yaml (default: beanstalk)"
    )
    parser.add_argument(
        '-n', '--name',
        required=True,
        metavar='<name>',
        help='Name of suite run the job is part of'
    )
    parser.add_argument(
        '-d', '--description',
        metavar='<desc>',
        help='Job description'
    )
    parser.add_argument(
        '-o', '--owner',
        metavar='<owner>',
        help='Job owner'
    )
    parser.add_argument(
        '-w', '--worker',
        default='plana',
        metavar='<worker>',
        help='Which worker to use (type of machine) (default: plana)'
    )
    parser.add_argument(
        '-p', '--priority',
        type=int,
        default=1000,
        metavar='<priority>',
        help='Job priority (lower is sooner) (default: 1000)'
    )
    parser.add_argument(
        '-N', '--num',
        type=int,
        default=1,
        metavar='<num>',
        help='Number of times to run/queue the job (default: 1)'
    )
    parser.add_argument(
        '--first-in-suite',
        action='store_true',
        help='Mark the first job in a suite so suite can note down the rerun-related info'
    )
    parser.add_argument(
        '--last-in-suite',
        action='store_true',
        help='Mark the last job in a suite so suite post-processing can be run'
    )
    parser.add_argument(
        '--email',
        metavar='<email>',
        help='Where to send the results of a suite. Only applies to the last job in a suite.'
    )
    parser.add_argument(
        '--timeout',
        metavar='<timeout>',
        help='How many seconds to wait for jobs to finish before emailing results. Only applies to the last job in a suite.'
    )
    parser.add_argument(
        '--seed',
        metavar='<seed>',
        help='The random seed for rerunning the suite. Only applies to the first job in a suite.'
    )
    parser.add_argument(
        '--subset',
        metavar='<subset>',
        help='The subset option passed to teuthology-suite. Only applies to the first job in a suite.'
    )
    parser.add_argument(
        '--no-nested-subset',
        action='store_true',
        help='The no-nested-subset option passed to teuthology-suite. Only applies to the first job in a suite.'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Instead of scheduling, just output the job config'
    )
    args = parser.parse_args(argv)
    teuthology.schedule.main(args.__dict__)
