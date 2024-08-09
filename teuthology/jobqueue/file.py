from typing import Optional

import yaml

from teuthology import beanstalk
from teuthology.jobqueue import base


class JobQueue(base.JobQueue):
    def __init__(self, path: str, direction: base.QueueDirection) -> None:
        if direction != base.QueueDirection.IN:
            raise ValueError('only output supported')
        self._base_path = path
        self._count_file_path = f'{path}.count'
        self._count = 0
        try:
            with open(self._count_file_path, 'r') as fh:
                self._count = int(fh.read() or 0)
        except FileNotFoundError:
            pass

    def put(self, job_config: base.JobSpec) -> int:
        jid = self._count = self._count + 1
        count_file_path = f'{self._base_path}.count'
        job_config['job_id'] = str(jid)
        job = yaml.safe_dump(job_config)
        with open(self._base_path, 'a') as fh:
            fh.write('---\n')
            fh.write(job)
        with open(self._count_file_path, 'w') as fh:
            fh.write(str(jid))
        print(f'Job scheduled with name {job_config["name"]} and ID {jid}')

    @property
    def tube(self) -> str:
        return ''

    @property
    def direction(self) -> base.QueueDirection:
        return base.QueueDirection.IN
