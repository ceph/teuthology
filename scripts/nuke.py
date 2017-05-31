import docopt

import teuthology.nuke

doc = """
usage:
  teuthology-nuke --help
  teuthology-nuke [-v] [--owner OWNER] [-n NAME] [-u] [-i] [-r] [-s]
                       [-p PID] [--dry-run] (-t CONFIG... | -a DIR)
  teuthology-nuke [-v] [-u] [-i] [-r] [-s] [--dry-run] --owner OWNER --stale
  teuthology-nuke [-v] [--dry-run] --stale-openstack

Reset test machines

optional arguments:
  -h, --help            Show this help message and exit
  -v, --verbose         Be more verbose
  -t CONFIG [CONFIG ...], --targets CONFIG [CONFIG ...]
                        Yaml config containing machines to nuke
  -a DIR, --archive DIR
                        Archive path for a job to kill and nuke
  --stale               Attempt to find and nuke 'stale' machines
                        (e.g. locked by jobs that are no longer running)
  --stale-openstack     Nuke 'stale' OpenStack instances and volumes
                        and unlock OpenStack targets with no instance
  --dry-run             Don't actually nuke anything; just print the list of
                        targets that would be nuked
  --owner OWNER         Job owner
  -p PID, --pid PID     Pid of the process to be killed
  -r, --reboot-all      Reboot all machines
  -s, --synch-clocks    Synchronize clocks on all machines
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
