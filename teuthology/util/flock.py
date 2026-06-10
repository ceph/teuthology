import fcntl
from typing import Optional
from types import TracebackType


class FileLock(object):
    def __init__(self, filename: str, noop: bool = False) -> None:
        self.filename = filename
        self.file = None
        self.noop = noop

    def __enter__(self) -> 'FileLock':
        if not self.noop:
            assert self.file is None
            self.file = open(self.filename, 'w')
            fcntl.lockf(self.file, fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type: Optional[type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]) -> None:
        if not self.noop:
            assert self.file is not None
            fcntl.lockf(self.file, fcntl.LOCK_UN)
            self.file.close()
            self.file = None
