import argparse
import sys

import teuthology.reimage

desc = """
Reimage nodes without locking using specified distro type and version.
The nodes must be locked by the current user, otherwise an error occurs.
Custom owner can be specified in order to provision someone else nodes.
Reimaging unlocked nodes cannot be provided.
"""

def main(argv=sys.argv[1:]):
    parser = argparse.ArgumentParser(
        description=desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'nodes',
        nargs='+',
        metavar='<nodes>',
        help='Nodes to reimage'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Be more verbose'
    )
    parser.add_argument(
        '--os-type',
        required=True,
        metavar='<os-type>',
        help='Distro type like: rhel, ubuntu, etc.'
    )
    parser.add_argument(
        '--os-version',
        required=True,
        metavar='<os-version>',
        help='Distro version like: 7.6, 16.04, etc.'
    )
    parser.add_argument(
        '--owner',
        metavar='user@host',
        help='Owner of the locked machines'
    )
    args = parser.parse_args(argv)
    return teuthology.reimage.main(args.__dict__)
