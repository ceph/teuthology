import os, sys

# Tell gevent not to patch os.waitpid() since it is susceptible to race
# conditions. See:
# http://www.gevent.org/gevent.monkey.html#gevent.monkey.patch_os
os.environ['GEVENT_NOWAITPID'] = 'true'

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
from gevent import monkey
patch_threads=True
for arg in sys.argv:
    if "teuthology_api" in arg:
        patch_threads=False
monkey.patch_all(
    dns=False,
    # Don't patch subprocess to avoid http://tracker.ceph.com/issues/14990
    subprocess=False,
    thread=patch_threads,
)
#----
#import traceback
#traceback.print_stack() 
#----

import sys
from gevent.hub import Hub

# Don't write pyc files
sys.dont_write_bytecode = True

from teuthology.orchestra import monkey
monkey.patch_all()

import logging
log = logging.getLogger(__name__)

def patch_gevent_hub_error_handler():
    Hub._origin_handle_error = Hub.handle_error

    def custom_handle_error(self, context, type, value, tb):
        if context is None or issubclass(type, Hub.SYSTEM_ERROR):
            self.handle_system_error(type, value)
        elif issubclass(type, Hub.NOT_ERROR):
            pass
        else:
            log.error("Uncaught exception (Hub)", exc_info=(type, value, tb))

    Hub.handle_error = custom_handle_error

patch_gevent_hub_error_handler()
