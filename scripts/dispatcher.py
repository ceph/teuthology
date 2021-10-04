"""
usage: teuthology-dispatcher --help
       teuthology-dispatcher --supervisor [-v] --bin-path BIN_PATH --job-config CONFIG --archive-dir DIR
       teuthology-dispatcher [-v] [--archive-dir DIR] --log-dir LOG_DIR --machine-type MACHINE_TYPE --queue-backend BACKEND

Start a dispatcher for the specified machine type. Grab jobs from a paddles/beanstalk
queue and run the teuthology tests they describe as subprocesses. The
subprocess invoked is a teuthology-dispatcher command run in supervisor
mode.

Supervisor mode: Supervise the job run described by its config. Reimage
target machines and invoke teuthology command. Unlock the target machines
at the end of the run.

standard arguments:
  -h, --help                     show this help message and exit
  -v, --verbose                  be more verbose
  -l, --log-dir LOG_DIR          path in which to store logs
  -a DIR, --archive-dir DIR      path to archive results in
  --machine-type MACHINE_TYPE    the machine type for the job
  --supervisor                   run dispatcher in job supervisor mode
  --bin-path BIN_PATH            teuthology bin path
  --job-config CONFIG            file descriptor of job's config file
  --exit-on-empty-queue          if the queue is empty, exit
  --queue-backend BACKEND        choose between paddles and beanstalk
"""

import docopt
import sys

import teuthology.dispatcher


def main():
    args = docopt.docopt(__doc__)
    sys.exit(teuthology.dispatcher.main(args))
