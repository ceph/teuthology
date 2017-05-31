import docopt

import teuthology
import teuthology.lock
import teuthology.lock.ops
import teuthology.orchestra.remote

import logging

doc = """
usage: teuthology-update-inventory -h
       teuthology-update-inventory [-v] REMOTE [REMOTE ...]

Update the given nodes' inventory information on the lock server


  -h, --help            Show this help message and exit
  -v, --verbose         Be more verbose
  REMOTE                Hostnames of machines whose information to update

"""


def main():
    args = docopt.docopt(doc)
    if args['--verbose']:
        teuthology.log.setLevel(logging.DEBUG)

    remotes = args.get('REMOTE')
    for rem_name in remotes:
        remote = teuthology.orchestra.remote.Remote(rem_name)
        inventory_info = remote.inventory_info
        teuthology.lock.ops.update_inventory(inventory_info)

