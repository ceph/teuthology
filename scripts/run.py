import argparse

import teuthology
import teuthology.run


def main():
    parser = argparse.ArgumentParser(
        description='Run ceph integration tests',
    )
    parser.add_argument(
        'config',
        nargs='+',
        metavar='<config>',
        help='one or more config files to read'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='be more verbose'
    )
    parser.add_argument(
        '--version',
        action='version',
        version=teuthology.__version__,
        help='the current installed version of teuthology'
    )
    parser.add_argument(
        '-a', '--archive',
        metavar='DIR',
        help='path to archive results in'
    )
    parser.add_argument(
        '--description',
        help='job description'
    )
    parser.add_argument(
        '--owner',
        help='job owner'
    )
    parser.add_argument(
        '--lock',
        action='store_true',
        help='lock machines for the duration of the run'
    )
    parser.add_argument(
        '--machine-type',
        help='Type of machine to lock/run tests on'
    )
    parser.add_argument(
        '--os-type',
        help='Distro/OS of machine to run test on'
    )
    parser.add_argument(
        '--os-version',
        help='Distro/OS version of machine to run test on'
    )
    parser.add_argument(
        '--block',
        action='store_true',
        help='block until locking machines succeeds (use with --lock)'
    )
    parser.add_argument(
        '--name',
        help='name for this teuthology run'
    )
    parser.add_argument(
        '--suite-path',
        help='Location of ceph-qa-suite on disk. If not specified, it will be fetched'
    )
    parser.add_argument(
        '--interactive-on-error',
        action='store_true',
        help='drop to a python shell on failure, which will halt the job; developer can then ssh to targets and examine cluster state'
    )
    args = parser.parse_args()
    teuthology.run.main(args.__dict__)
