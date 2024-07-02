import argparse
import logging
import sys

import teuthology
from teuthology.lock import query, ops

def main():
    args = parse_args(sys.argv[1:])
    if args.verbose:
        teuthology.log.setLevel(logging.DEBUG)
    log = logging.getLogger(__name__)
    stale = query.find_stale_locks(args.owner)
    if not stale:
        return
    by_owner = {}
    for node in stale:
        if args.owner and node['locked_by'] != args.owner:
            log.warning(
                f"Node {node['name']} expected to be locked by {args.owner} "
                f"but found {node['locked_by']} instead"
            )
            continue
        by_owner.setdefault(node['locked_by'], []).append(node)
    if args.dry_run:
        log.info("Would attempt to unlock:")
        for owner, nodes in by_owner.items():
            for node in nodes:
                log.info(f"{node['name']}\t{node['description']}")
    else:
        for owner, nodes in by_owner.items():
            ops.unlock_safe([node["name"] for node in nodes], owner)

def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Find and unlock nodes that are still locked by jobs that are no "
            "longer active",
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        default=False,
        help='Be more verbose',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=False,
        help="List nodes that would be unlocked if the flag were omitted",
    )
    parser.add_argument(
        '--owner',
        help='Optionally, find nodes locked by a specific user',
    )
    return parser.parse_args(argv)

if __name__ == "__main__":
    main()
