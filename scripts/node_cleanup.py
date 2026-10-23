import argparse
import logging
import sys

import teuthology
from teuthology.config import config
from teuthology.lock import query, ops


def main():
    args = parse_args(sys.argv[1:])
    log = logging.getLogger(__name__)
    if args.verbose:
        log.setLevel(logging.DEBUG)
        teuthology.log.setLevel(logging.DEBUG)
    else:
        teuthology.log.setLevel(100)
    # regardless of verbosity we do not want to log console stuff
    logging.getLogger("teuthology.orchestra.console").setLevel(logging.WARNING)
    logger = logging.getLogger()
    for handler in logger.handlers:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
        )
    try:
        stale = query.find_stale_locks(
            args.owner,
            machine_type=args.machine_type
        )
    except Exception:
        log.exception(f"Error while check for stale locks held by {args.owner}")
        return
    log.debug(f"Stale nodes: {len(stale)}")
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
                node_job = node['description'].replace(
                    config.archive_base, config.results_ui_server)
                log.info(f"{node['name']}\t{node_job}")
    else:
        for owner, nodes in by_owner.items():
            ops.unlock_safe([node["name"] for node in nodes], owner)
    log.info(f"Unlocked {len(stale)} nodes")

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
    parser.add_argument(
        '-m', '--machine-type',
        help='Optionally, find nodes in a comma-separated list of machine types',
    )
    return parser.parse_args(argv)

if __name__ == "__main__":
    main()
