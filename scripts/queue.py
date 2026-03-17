import argparse

import teuthology.config
import teuthology.beanstalk

desc = """
List Jobs in queue.
If -D is passed, then jobs with PATTERN in the job name are deleted from the
queue.
"""


def main():
    parser = argparse.ArgumentParser(
        description=desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '-m', '--machine_type',
        default='multi',
        help='Which machine type queue to work on (default: multi)'
    )
    parser.add_argument(
        '-D', '--delete',
        metavar='PATTERN',
        help='Delete Jobs with PATTERN in their name'
    )
    parser.add_argument(
        '-d', '--description',
        action='store_true',
        help='Show job descriptions'
    )
    parser.add_argument(
        '-r', '--runs',
        action='store_true',
        help='Only show run names'
    )
    parser.add_argument(
        '-f', '--full',
        action='store_true',
        help='Print the entire job config. Use with caution.'
    )
    parser.add_argument(
        '-s', '--status',
        action='store_true',
        help='Prints the status of the queue'
    )
    parser.add_argument(
        '-p', '--pause',
        type=int,
        metavar='SECONDS',
        help='Pause queues for a number of seconds. A value of 0 will unpause. If -m is passed, pause that queue, otherwise pause all queues.'
    )
    args = parser.parse_args()
    teuthology.beanstalk.main(args.__dict__)
