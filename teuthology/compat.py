# flake8: noqa

try:
    from cStringIO import StringIO
    BytesIO = StringIO
    from StringIO import StringIO as PyStringIO
    PyBytesIO = PyStringIO
except ImportError:
    from io import StringIO, BytesIO
    PyStringIO = StringIO
    PyBytesIO = BytesIO

from io import StringIO as TextIO


if str is bytes:
    def stringify(s):
        return s
else:
    def stringify(s):
        if isinstance(s, bytes):
            return s.decode('utf-8', 'replace')
        return s
