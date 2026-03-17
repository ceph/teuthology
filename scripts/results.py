import argparse
import teuthology.results


def main():
    parser = argparse.ArgumentParser(
        description='Email teuthology suite results',
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='be more verbose'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Instead of sending the email, just print it'
    )
    parser.add_argument(
        '--email',
        help='address to email test failures to'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=0,
        help='how many seconds to wait for all tests to finish (default: 0)'
    )
    parser.add_argument(
        '--archive-dir',
        required=True,
        metavar='DIR',
        help='path under which results for the suite are stored'
    )
    parser.add_argument(
        '--name',
        required=True,
        help='name of the suite'
    )
    parser.add_argument(
        '--subset',
        help='subset passed to teuthology-suite'
    )
    parser.add_argument(
        '--seed',
        help='random seed used in teuthology-suite'
    )
    parser.add_argument(
        '--no-nested-subset',
        action='store_true',
        help='disable nested subsets used in teuthology-suite'
    )
    args = parser.parse_args()
    teuthology.results.main(args.__dict__)
