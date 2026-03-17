import argparse

import teuthology
import teuthology.lock
import teuthology.lock.ops
import teuthology.misc
import teuthology.orchestra.remote

import logging

def main():
    parser = argparse.ArgumentParser(
        description="Update the given nodes' inventory information on the lock server",
    )
    parser.add_argument(
        'remotes',
        nargs='+',
        metavar='REMOTE',
        help='hostnames of machines whose information to update'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='be more verbose'
    )
    parser.add_argument(
        '-m', '--machine-type',
        metavar='<type>',
        help='optionally specify a machine type when submitting nodes for the first time'
    )
    args = parser.parse_args()

    if args.verbose:
        teuthology.log.setLevel(logging.DEBUG)

    machine_type = args.machine_type
    remotes = args.remotes
    for rem_name in remotes:
        rem_name = teuthology.misc.canonicalize_hostname(rem_name)
        remote = teuthology.orchestra.remote.Remote(rem_name)
        remote.connect()
        inventory_info = remote.inventory_info
        if machine_type:
          inventory_info['machine_type'] = machine_type
        teuthology.lock.ops.update_inventory(inventory_info)
