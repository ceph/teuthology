import contextlib
import sys
import logging
import time

from teuthology.config import config
from teuthology.exceptions import MaxWhileTries


log = logging.getLogger(__name__)

@contextlib.contextmanager
def nested(*managers):
    """
    Like contextlib.nested but takes callables returning context
    managers, to avoid the major reason why contextlib.nested was
    deprecated.

    This version also logs any exceptions early, much like run_tasks,
    to ease debugging. TODO combine nested and run_tasks.
    """
    exits = []
    vars = []
    exc = (None, None, None)
    try:
        for mgr_fn in managers:
            mgr = mgr_fn()
            exit = mgr.__exit__
            enter = mgr.__enter__
            vars.append(enter())
            exits.append(exit)
        yield vars
    except Exception:
        log.exception('Saw exception from nested tasks')
        exc = sys.exc_info()
        # FIXME this needs to be more generic
        if config.ctx and config.ctx.config.get('interactive-on-error'):
            config.ctx.config['interactive-on-error'] = False
            from teuthology.task import interactive
            log.warning('Saw failure, going into interactive mode...')
            interactive.task(ctx=config.ctx, config=None)
    finally:
        while exits:
            exit = exits.pop()
            try:
                if exit(*exc):
                    exc = (None, None, None)
            except Exception:
                exc = sys.exc_info()
        if exc != (None, None, None):
            # Don't rely on sys.exc_info() still containing
            # the right information. Another exception may
            # have been raised and caught by an exit method
            raise exc[1]


class safe_while(object):
    """
    A context manager to remove boiler plate code that deals with `while` loops
    that need a given number of tries or total timeout and some seconds to sleep
    between each one of those tries.

    The most simple example possible will try 10 times sleeping for 6 seconds:

        >>> from teuthology.contexutil import safe_while
        >>> with safe_while() as proceed:
        ...    while proceed():
        ...        # repetitive code here
        ...        print("hello world")
        ...
        Traceback (most recent call last):
        ...
        MaxWhileTries: reached maximum tries (5) after waiting for 75 seconds

    Yes, this adds yet another level of indentation but it allows you to
    implement while loops exactly the same as before with just 1 more
    indentation level and one extra call. Everything else stays the same,
    code-wise. So adding this helper to existing code is simpler.

    :param sleep:     The amount of time to sleep between tries. Default 6
    :param increment: The amount to add to the sleep value on each try.
                      Default 0.
    :param tries:     The amount of tries before giving up. Default 10.
    :param timeout:   Total seconds to try for, overrides the tries parameter
                      if specified. Default 0.
    :param action:    The name of the action being attempted. Default none.
    :param _raise:    Whether to raise an exception (or log a warning).
                      Default True.
    :param _sleeper:  The function to use to sleep. Only used for testing.
                      Default time.sleep
    """

    def __init__(self, sleep=6, increment=0, tries=10, timeout=0, action=None,
                 _raise=True, _sleeper=None):
        self.sleep = sleep
        self.increment = increment
        self.tries = tries
        self.timeout = timeout
        self.counter = 0
        self.sleep_current = sleep
        self.action = action
        self._raise = _raise
        self.sleeper = _sleeper or time.sleep
        self.total_seconds = sleep

    def _make_error_msg(self):
        """
        Sum the total number of seconds we waited while providing the number
        of tries we attempted
        """
        msg = 'reached maximum tries ({tries})' + \
            ' after waiting for {total} seconds'
        if self.action:
            msg = "'{action}' " + msg

        msg = msg.format(
            action=self.action,
            tries=self.counter - 1,
            total=self.total_seconds,
        )
        return msg

    def __call__(self):
        self.counter += 1
        if self.counter == 1:
            return True
        def must_stop():
            return self.tries > 0 and self.counter > self.tries
        if ((self.timeout > 0 and
             self.total_seconds >= self.timeout) or
            (self.timeout == 0 and must_stop())):
            error_msg = self._make_error_msg()
            if self._raise:
                raise MaxWhileTries(error_msg)
            else:
                log.warning(error_msg)
                return False
        self.sleep_current += self.increment
        if self.timeout > 0:
            self.sleep_current = min(self.timeout - self.total_seconds, self.sleep_current)
        self.total_seconds += self.sleep_current
        self.sleeper(self.sleep_current)
        return True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
