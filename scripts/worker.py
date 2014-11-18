"""
usage: teuthology-worker [-h] [-v] --archive-dir=DIR -l LOG_DIR -t TUBE

Grab jobs from a beanstalk queue and run the teuthology tests they describe.
One job is run at a time.

optional arguments:
  -h, --help            show this help message and exit
  -v, --verbose         be more verbose
  --archive-dir=DIR     path under which to archive results
  -l LOG_DIR --log-dir=LOG_DIR
                        path in which to store logs
  -t TUBE --tube=TUBE   which beanstalk tube to read jobs from
"""
import docopt

import teuthology.worker


def main():
    args = docopt.docopt(__doc__)
    teuthology.worker.main(args)
