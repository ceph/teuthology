import contextlib

from teuthology.exporter import REGISTRY

class SingletonMeta(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]

class TeuthologyMetric(metaclass=SingletonMeta):
    def __init__(self):
        if REGISTRY:
            self._init()

    def _init(self):
        raise NotImplementedError

    def update(self):
        if REGISTRY:
            self._update()

    def _update(self):
        raise NotImplementedError

    def record(self, **kwargs):
        if REGISTRY:
            self._record(**kwargs)

    def _record(self, **_):
        raise NotImplementedError

    @contextlib.contextmanager
    def time(self, **labels):
        if REGISTRY:
            yield self._time(**labels)
        else:
            yield

    def _time(self):
        raise NotImplementedError
