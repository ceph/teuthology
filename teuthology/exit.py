import logging
import os
import signal
from typing import Callable, Optional
from types import FrameType


log = logging.getLogger(__name__)


class Exiter(object):
    """
    A helper to manage any signal handlers we need to call upon receiving a
    given signal
    """
    def __init__(self) -> None:
        self.handlers = list()

    def add_handler(self, signals: int | list[int], func: Callable[[int, Optional[FrameType]], None]) -> 'Handler':
        """
        Adds a handler function to be called when any of the given signals are
        received.

        The handler function should have a signature like::

            my_handler(signal, frame)
        """
        if isinstance(signals, int):
            signals = [signals]

        for signal_ in signals:
            signal.signal(signal_, self.default_handler)

        handler = Handler(self, func, signals)
        log.debug(
            "Installing handler: %s",
            repr(handler),
        )
        self.handlers.append(handler)
        return handler

    def default_handler(self, signal_: int, frame: Optional[FrameType]) -> None:
        log.debug(
            "Got signal %s; running %s handler%s...",
            signal_,
            len(self.handlers),
            '' if len(self.handlers) == 1 else 's',
        )
        for handler in self.handlers:
            handler.func(signal_, frame)
        log.debug("Finished running handlers")
        # Restore the default handler
        signal.signal(signal_, 0)
        # Re-send the signal to our main process
        os.kill(os.getpid(), signal_)


class Handler(object):
    def __init__(self, exiter: Exiter, func: Callable[[int, Optional[FrameType]], None], signals: list[int]) -> None:
        self.exiter = exiter
        self.func = func
        self.signals = signals

    def remove(self) -> None:
        try:
            log.debug("Removing handler: %s", self)
            self.exiter.handlers.remove(self)
        except ValueError:
            pass

    def __repr__(self) -> str:
        return "{c}(exiter={e}, func={f}, signals={s})".format(
            c=self.__class__.__name__,
            e=self.exiter,
            f=self.func,
            s=self.signals,
        )


exiter = Exiter()
