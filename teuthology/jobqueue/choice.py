from teuthology.config import config as teuth_config

from teuthology.jobqueue.base import QueueDirection, JobQueue
from teuthology.jobqueue import beanstalk, sqlite
from teuthology.jobqueue import file as fileq


def from_backend(
    backend: str, tube: str, direction: QueueDirection
) -> JobQueue:
    if backend in ('beanstalk', ''):
        return beanstalk.JobQueue.connect(tube, direction)
    if backend.startswith('@'):
        return fileq.JobQueue(backend.lstrip('@'), direction)
    if backend.startswith('sqlite:'):
        return sqlite.JobQueue(backend, tube, direction)
    raise ValueError(
        f"Unexpected queue backend: {backend!r}"
        " (expected 'beanstalk', '@<path-to-file>',"
        " or 'sqlite://<path-to-file>'"
    )


def from_config(
    tube: str, direction: QueueDirection, backend: str = ''
) -> JobQueue:
    if not backend:
        backend = teuth_config.job_queue_backend or ''
    return from_backend(backend, tube, direction)
