"""
usage: teuthology-worker --help
       teuthology-worker [options] --archive-dir DIR --bin-path BIN_PATH

Run ceph integration tests

optional arguments:
  -h, --help                     show this help message and exit
  -v, --verbose                  be more verbose
  --archive-dir DIR              path to archive results in
  --bin-path BIN_PATH            teuth-bin-path
"""

import docopt

import teuthology.worker


def main():
    args = docopt.docopt(__doc__)
    teuthology.worker.main(args)
