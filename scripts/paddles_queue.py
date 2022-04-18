import docopt

import teuthology.config
import teuthology.queue.paddles_queue
doc = """
usage: teuthology-paddles-queue -h
       teuthology-paddles-queue -s -m MACHINE_TYPE
       teuthology-paddles-queue [-d|-f] -m MACHINE_TYPE -U USER
       teuthology-paddles-queue -m MACHINE_TYPE -P PRIORITY [-U USER|-R RUN_NAME]
       teuthology-paddles-queue [-r] -m MACHINE_TYPE -U USER
       teuthology-paddles-queue -m MACHINE_TYPE -D PATTERN -U USER
       teuthology-paddles-queue -p [-t SECONDS] -m MACHINE_TYPE -U USER
       teuthology-paddles-queue -u -m MACHINE_TYPE -U USER

List Jobs in queue.
If -D is passed, then jobs with PATTERN in the job name are deleted from the
queue.

Arguments:
  -m, --machine_type MACHINE_TYPE
                        Which machine type queue to work on.

optional arguments:
  -h, --help            Show this help message and exit
  -D, --delete PATTERN  Delete Jobs with PATTERN in their name
  -d, --description     Show job descriptions
  -r, --runs            Only show run names
  -f, --full            Print the entire job config. Use with caution.
  -s, --status          Prints the status of the queue
  -t, --time SECONDS    Pause queues for a number of seconds.
                        If -m is passed, pause that queue,
                        otherwise pause all queues.
  -p, --pause           Pause queue
  -u, --unpause         Unpause queue
  -P, --priority PRIORITY
                        Change priority of queued jobs
  -U, --user USER       User who owns the jobs
  -R, --run-name RUN_NAME
                        Used to change priority of all jobs in the run.
"""


def main():
    args = docopt.docopt(doc)
    teuthology.paddles_queue.main(args)
