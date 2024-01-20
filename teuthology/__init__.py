from __future__ import print_function
import os
try:
    import importlib.metadata as importlib_metadata
except ImportError:
    import importlib_metadata

__version__ = importlib_metadata.version("teuthology")

# Use manhole to give us a way to debug hung processes
# https://pypi.python.org/pypi/manhole
try:
    import manhole
    manhole.install(
        verbose=False,
        # Listen for SIGUSR1
        oneshot_on="USR1"
    )
except ImportError:
    pass
import sys

# Don't write pyc files
sys.dont_write_bytecode = True

import logging

# If we are running inside a virtualenv, ensure we have its 'bin' directory in
# our PATH. This doesn't happen automatically if scripts are called without
# first activating the virtualenv.
exec_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
if os.path.split(exec_dir)[-1] == 'bin' and exec_dir not in os.environ['PATH']:
    os.environ['PATH'] = ':'.join((exec_dir, os.environ['PATH']))

# We don't need to see log entries for each connection opened
logging.getLogger('requests.packages.urllib3.connectionpool').setLevel(
    logging.WARN)
# if requests doesn't bundle it, shut it up anyway
logging.getLogger('urllib3.connectionpool').setLevel(
    logging.WARN)
# We also don't need the "Converted retries value" messages
logging.getLogger('urllib3.util.retry').setLevel(
    logging.WARN)
# TODO re-check: gevent-related debug statement from asyncio
logging.getLogger('asyncio').setLevel(
    logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d %(levelname)s:%(name)s:%(message)s')
log = logging.getLogger(__name__)

log.debug('teuthology version: %s', __version__)


def setup_log_file(log_path):
    root_logger = logging.getLogger()
    handlers = root_logger.handlers
    for handler in handlers:
        if isinstance(handler, logging.FileHandler) and \
                handler.stream.name == log_path:
            log.debug("Already logging to %s; not adding new handler",
                      log_path)
            return
    formatter = logging.Formatter(
        fmt=u'%(asctime)s.%(msecs)03d %(levelname)s:%(name)s:%(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S')
    handler = logging.FileHandler(filename=log_path)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.info('teuthology version: %s', __version__)


def install_except_hook():
    """
    Install an exception hook that first logs any uncaught exception, then
    raises it.
    """
    def log_exception(exc_type, exc_value, exc_traceback):
        if not issubclass(exc_type, KeyboardInterrupt):
            log.critical("Uncaught exception", exc_info=(exc_type, exc_value,
                                                         exc_traceback))
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
    sys.excepthook = log_exception
