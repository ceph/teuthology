import docopt

import teuthology.nuke

doc = """
usage: teuthology-nuke --help
       teuthology-nuke -v [--owner OWNER] [-n NAME] [-u] [-i] [-r] [-s]
                            [-t CONFIG...] [-a DIR] [-p PID]
       teuthology-nuke --owner OWNER [-v] [-n NAME] [-u] [-i] [-r] [-s]
                            [-t CONFIG...] [-a DIR] [-p PID]
       teuthology-nuke -n NAME [-v] [--owner OWNER] [-u] [-i] [-r] [-s]
                            [-t CONFIG...] [-a DIR] [-p PID]
       teuthology-nuke -u [-v] [--owner OWNER] [-n NAME] [-i] [-r] [-s]
                            [-t CONFIG...] [-a DIR] [-p PID]
       teuthology-nuke -i [-v] [--owner OWNER] [-n NAME] [-u] [-r] [-s]
                            [-t CONFIG...] [-a DIR] [-p PID]
       teuthology-nuke -r [-v] [--owner OWNER] [-n NAME] [-u] [-i] [-s]
                            [-t CONFIG...] [-a DIR] [-p PID]
       teuthology-nuke -s [-v] [--owner OWNER] [-n NAME] [-u] [-i] [-r]
                            [-t CONFIG...] [-a DIR] [-p PID]
       teuthology-nuke (-t CONFIG...) [-v] [--owner OWNER] [-n NAME] [-u] [-i] [-r] [-s]
                            [-a DIR] [-p PID]
       teuthology-nuke -a DIR [-v] [--owner OWNER] [-n NAME] [-u] [-i] [-r] [-s]
                            [-t CONFIG...] [-p PID]
       teuthology-nuke -p PID [-v] [--owner OWNER] [-n NAME] [-u] [-i] [-r] [-s]
                            [-t CONFIG...] [-a DIR] 
       teuthology-nuke [-v] [-u] [-i] [-r] [-s] --owner OWNER --stale

Reset test machines

optional arguments:
  -h, --help            show this help message and exit
  -v, --verbose         be more verbose
  -t CONFIG [CONFIG ...], --targets CONFIG [CONFIG ...]
                        yaml config containing machines to nuke
  -a DIR, --archive DIR
                        archive path for a job to kill and nuke
  --stale               attempt to find and nuke 'stale' machines
                        (e.g. locked by jobs that are no longer running)
  --owner OWNER         job owner
  -p PID, --pid PID     pid of the process to be killed
  -r, --reboot-all      reboot all machines
  -s, --synch-clocks    synchronize clocks on all machines
  -u, --unlock          Unlock each successfully nuked machine, and output
                        targets thatcould not be nuked.
  -n NAME, --name NAME  Name of run to cleanup
  -i, --noipmi          Skip ipmi checking

Examples:
teuthology-nuke -t target.yaml --unlock --owner user@host
teuthology-nuke -t target.yaml --pid 1234 --unlock --owner user@host
"""


def main():
    args = docopt.docopt(doc)
    teuthology.nuke.main(args)
