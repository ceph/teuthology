from typing import Dict, Any, Optional

import abc
import enum


JobSpec = Dict[str, Any]


class QueueDirection(enum.Enum):
    IN = 1
    OUT = 2
    BIDIR = 3


class Job(abc.ABC):
    jid: int

    @abc.abstractmethod
    def bury(self) -> None: ...

    @abc.abstractmethod
    def delete(self) -> None: ...

    @abc.abstractmethod
    def job_config(self) -> JobSpec: ...


class JobQueue(abc.ABC):
    @abc.abstractmethod
    def put(self, job_config: JobSpec) -> int: ...

    @abc.abstractmethod
    def get(self) -> Optional[Job]: ...

    @property
    @abc.abstractmethod
    def tube(self) -> str: ...

    @property
    @abc.abstractmethod
    def direction(self) -> QueueDirection: ...
