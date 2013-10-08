import argparse

import teuthology.suite


def main():
    teuthology.suite.main(parse_args())


def parse_args():
    parser = argparse.ArgumentParser(description="""
Run a suite of ceph integration tests.

A suite is a set of collections.

A collection is a directory containing facets.

A facet is a directory containing config snippets.

Running a collection means running teuthology for every configuration
combination generated by taking one config snippet from each facet.

Any config files passed on the command line will be used for every
combination, and will override anything in the suite.
""")
    parser.add_argument(
        '-v', '--verbose',
        action='store_true', default=None,
        help='be more verbose',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true', default=None,
        help='do a dry run; do not schedule anything',
    )
    parser.add_argument(
        '--name',
        help='name for this suite',
        required=True,
    )
    parser.add_argument(
        '--base',
        default=None,
        help='base directory for the collection(s)'
    )
    parser.add_argument(
        '--collections',
        metavar='DIR',
        nargs='+',
        required=True,
        help='the collections to run',
    )
    parser.add_argument(
        '--owner',
        help='job owner',
    )
    parser.add_argument(
        '--email',
        help='address to email test failures to',
    )
    parser.add_argument(
        '--timeout',
        help='how many seconds to wait for jobs to finish before emailing ' +
        'results',
    )
    parser.add_argument(
        '-n', '--num',
        default=1,
        type=int,
        help='number of times to run/queue each job'
    )
    parser.add_argument(
        '-w', '--worker',
        default='plana',
        help='which worker to use (type of machine)',
    )
    parser.add_argument(
        'config',
        metavar='CONFFILE',
        nargs='*',
        default=[],
        help='config file to read',
    )

    return parser.parse_args()
