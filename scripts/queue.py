import docopt

import teuthology.queue.beanstalk
import teuthology.queue.paddles
from teuthology.config import config

doc = """
usage: teuthology-queue -h
       teuthology-queue [-s|-d|-f] -m MACHINE_TYPE
       teuthology-queue [-r] -m MACHINE_TYPE
       teuthology-queue -m MACHINE_TYPE -D PATTERN
       teuthology-queue -p SECONDS [-m MACHINE_TYPE] [-U USER]
       teuthology-queue -m MACHINE_TYPE -P PRIORITY [-U USER|-R RUN_NAME]

List Jobs in queue.
If -D is passed, then jobs with PATTERN in the job name are deleted from the
queue.

Arguments:
  -m, --machine_type MACHINE_TYPE [default: multi]
                        Which machine type queue to work on.

optional arguments:
  -h, --help            Show this help message and exit
  -D, --delete PATTERN  Delete Jobs with PATTERN in their name
  -d, --description     Show job descriptions
  -r, --runs            Only show run names
  -f, --full            Print the entire job config. Use with caution.
  -s, --status          Prints the status of the queue
  -p, --pause SECONDS   Pause queues for a number of seconds. A value of 0
                        will unpause. If -m is passed, pause that queue,
                        otherwise pause all queues.
  -P, --priority PRIORITY
                        Change priority of queued jobs (only in Paddles queues)
  -U, --user USER       User who owns the jobs
  -R, --run-name RUN_NAME
                        Used to change priority of all jobs in the run.
"""


def main():
    args = docopt.docopt(doc)
    if config.backend == 'beanstalk':
      teuthology.queue.beanstalk.main(args)
    else:
      teuthology.queue.paddles.main(args)
