import argparse
import teuthology.ls


def _build_parser():
    parser = argparse.ArgumentParser(
        description='List teuthology job results',
    )
    parser.add_argument(
        'archive_dir',
        metavar='<archive_dir>',
        help='path under which to archive results'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='show reasons tests failed'
    )
    return parser


def parse_args(argv=None):
    return _build_parser().parse_args(argv)


def main():
    args = parse_args()
    teuthology.ls.main(args.__dict__)
