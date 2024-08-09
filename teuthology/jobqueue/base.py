from typing import Dict, Any, Optional

import enum


JobSpec = Dict[str, Any]


class QueueDirection(enum.Enum):
    IN = 1
    OUT = 2
    BIDIR = 3


class Job:
    jid: int

    def bury(self) -> None:
        raise NotImplementedError()

    def delete(self) -> None:
        raise NotImplementedError()

    def job_config(self) -> JobSpec:
        raise NotImplementedError()


class JobQueue:
    def put(self, job_config: JobSpec) -> int:
        raise NotImplementedError()

    def get(self) -> Optional[Job]:
        raise NotImplementedError()

    @property
    def tube(self) -> str:
        raise NotImplementedError()

    @property
    def direction(self) -> QueueDirection:
        raise NotImplementedError()
