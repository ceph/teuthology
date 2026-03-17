import argparse

import teuthology.exporter

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--interval',
        type=int,
        default=60,
        help='update metrics this often, in seconds'
    )
    args = parser.parse_args()
    teuthology.exporter.main(args)
