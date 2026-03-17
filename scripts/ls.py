import argparse
import teuthology.ls


def main():
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
    args = parser.parse_args()
    teuthology.ls.main(args.__dict__)
