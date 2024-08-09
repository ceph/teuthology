from typing import Optional, Self

import yaml

from teuthology import beanstalk
from teuthology.jobqueue import base


class Job(base.Job):
    jid: int

    def __init__(self, job) -> None:
        self._job = job
        self.jid = job.jid

    def bury(self) -> None:
        self._job.bury()

    def delete(self) -> None:
        self._job.delete()

    def job_config(self) -> base.JobSpec:
        return yaml.safe_load(self._job.body)


class JobQueue(base.JobQueue):
    def __init__(
        self, connection, tube: str, direction: base.QueueDirection
    ) -> None:
        self._connection = connection
        self._direction = direction
        if direction == base.QueueDirection.IN:
            self._connection.use(tube)
            self._tube = tube
        if direction == base.QueueDirection.OUT:
            self._tube = beanstalk.watch_tube(tube)
        else:
            raise ValueError(
                f'invalid direction for beanstalk job queue: {direction}'
            )

    def put(self, job_config: base.JobSpec) -> int:
        if self._direction != base.QueueDirection.IN:
            raise ValueError('not an input queue')
        job = yaml.safe_dump(job_config)
        jid = beanstalk.put(
            job,
            ttr=60 * 60 * 24,
            priority=job_config['priority'],
        )
        return jid

    def get(self) -> Optional[Job]:
        if self._direction != base.QueueDirection.OUT:
            raise ValueError('not an output queue')
        return Job(connection.reserve(timeout=60))

    @property
    def tube(self) -> str:
        return self._tube

    @property
    def direction(self) -> base.QueueDirection:
        return self._direction

    @classmethod
    def connect(tube: str, direction: base.QueueDirection) -> Self:
        return cls(beanstalk.connect(), tube, direction)
