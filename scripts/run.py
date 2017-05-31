"""
usage: teuthology --help
       teuthology --version
       teuthology [options] [--] <config>...

Run ceph integration tests

positional arguments:
  <config> one or more config files to read

optional arguments:
  -h, --help                     Show this help message and exit
  -v, --verbose                  Be more verbose
  --version                      The current installed version of teuthology
  -a DIR, --archive DIR          Path to archive results in
  --description DESCRIPTION      Job description
  --owner OWNER                  Job owner
  --lock                         Lock machines for the duration of the run
  --machine-type MACHINE_TYPE    Type of machine to lock/run tests on.
  --os-type OS_TYPE              Distro/OS of machine to run test on.
  --os-version OS_VERSION        Distro/OS version of machine to run test on.
  --block                        Block until locking machines succeeds (use with --lock)
  --name NAME                    Name for this teuthology run
  --suite-path SUITE_PATH        Location of ceph-qa-suite on disk. If not specified,
                                 it will be fetched
"""
import docopt

import teuthology.run


def main():
    args = docopt.docopt(__doc__, version=teuthology.__version__)
    teuthology.run.main(args)
