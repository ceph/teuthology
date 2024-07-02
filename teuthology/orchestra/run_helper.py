"""
Contains classes that "help" RemoteProcess and rest of the code in run.py

This module was started as it was needed that Raw and quote be separated from
teuthology.orchestra.run so that these can be imported in
teuthology.exceptions without causing circular dependency.
"""

from pipes import quote as pipes_quote


class Raw(object):
    """
    Raw objects are passed to remote objects and are not processed locally.
    """
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return '{cls}({value!r})'.format(
            cls=self.__class__.__name__,
            value=self.value,
            )

    def __eq__(self, value):
        return self.value == value

    def __str__(self, value):
        return str(value)


def quote(args):
    """
    Internal quote wrapper.
    """
    def _quote(args):
        """
        Handle quoted string, testing for raw charaters.
        """
        for a in args:
            if isinstance(a, Raw):
                yield a.value
            else:
                yield pipes_quote(a)

    if isinstance(args, list):
        return ' '.join(_quote(args))
    else:
        return args


class Sentinel(object):
    """
    Sentinel -- used to define PIPE file-like object.
    """
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name


PIPE = Sentinel('PIPE')


class KludgeFile(object):
    """
    Wrap Paramiko's ChannelFile in a way that lets ``f.close()``
    actually cause an EOF for the remote command.
    """
    def __init__(self, wrapped):
        self._wrapped = wrapped

    def __getattr__(self, name):
        return getattr(self._wrapped, name)

    def close(self):
        """
        Close and shutdown.
        """
        self._wrapped.close()
        self._wrapped.channel.shutdown_write()
