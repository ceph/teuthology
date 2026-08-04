import argparse

import teuthology.exporter

def _build_parser():
    parser = argparse.ArgumentParser(
        description='Export teuthology metrics',
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=60,
        help='update metrics this often, in seconds [default: %(default)s]'
    )
    return parser


def parse_args(argv=None):
    return _build_parser().parse_args(argv)


def main():
    args = parse_args()
    teuthology.exporter.main(args)
