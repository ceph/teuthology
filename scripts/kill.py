import argparse

import teuthology.config
import teuthology.kill

desc = """
Kill running teuthology jobs:
1. Removes any queued jobs from the beanstalk queue
2. Kills any running jobs
3. Nukes any machines involved

NOTE: Must be run on the same machine that is executing the teuthology job
processes.
"""


def main():
    parser = argparse.ArgumentParser(
        description=desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '-p', '--preserve-queue',
        action='store_true',
        help='Preserve the queue - do not delete queued jobs'
    )
    parser.add_argument(
        '-r', '--run',
        help='The name(s) of the run(s) to kill'
    )
    parser.add_argument(
        '-j', '--job',
        action='append',
        help='The job_id of the job to kill'
    )
    parser.add_argument(
        '-J', '--jobspec',
        help="The 'jobspec' of the job to kill. A jobspec consists of both the name of the run and the job_id, separated by a '/'. e.g. 'my-test-run/1234'"
    )
    parser.add_argument(
        '-o', '--owner',
        help='The owner of the job(s)'
    )
    parser.add_argument(
        '-m', '--machine-type',
        help='The type of machine the job(s) are running on. This is required if killing a job that is still entirely in the queue.'
    )
    args = parser.parse_args()
    teuthology.kill.main(args.__dict__)
