"""
Sleep task
"""
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)


def task(ctx, config: Optional[dict]) -> None:
    """
    Sleep for some number of seconds.

    Example::


       tasks:
       - install:
       - ceph:
       - sleep:
           duration: 10
       - interactive:

    :param ctx: Context
    :param config: Configuration
    """
    if not config:
        config = {}
    assert isinstance(config, dict)
    duration = int(config.get('duration', 5))
    log.info('Sleeping for {} seconds'.format(duration))
    time.sleep(duration)
