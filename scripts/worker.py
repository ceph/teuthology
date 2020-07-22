"""
usage: teuthology-worker --help
       teuthology-worker -v --bin-path BIN_PATH --config-fd FD --archive-dir DIR

Run ceph integration tests

optional arguments:
  -h, --help                     show this help message and exit
  -v, --verbose                  be more verbose
  --archive-dir DIR              path to archive results in
  --bin-path BIN_PATH            teuth-bin-path
  --config-fd FD                 file descriptor of job's config file
"""

import docopt

import teuthology.worker


def main():
    args = docopt.docopt(__doc__)
    teuthology.worker.main(args)
