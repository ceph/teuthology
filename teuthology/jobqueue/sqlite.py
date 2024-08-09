from typing import Optional, Self, Tuple

import json
import sqlite3
import time

from teuthology.jobqueue import base


class Job(base.Job):
    jid: int

    def __init__(self, jq: 'JobQueue', jid: int, data: str) -> None:
        self._jq = jq
        self.jid = jid
        self._data = data

    def bury(self) -> None:
        self.delete()

    def delete(self) -> None:
        self._jq._delete(self.jid)

    def job_config(self) -> base.JobSpec:
        return json.loads(self._data)


class JobQueue(base.JobQueue):
    _retry_empty_sec = 30

    def __init__(
        self, path: str, tube: str, direction: base.QueueDirection
    ) -> None:
        self._path = path
        self._tube = tube
        # the sqlite job queue is always bidirectional
        self._direction = base.QueueDirection.BIDIR
        self._connect()
        self._create_jobs_table()

    def put(self, job_config: base.JobSpec) -> int:
        job = json.dumps(job_config)
        return self._insert(job)

    def get(self) -> Optional[Job]:
        result = self._select_job()
        if result is None:
            time.sleep(self._retry_empty_sec)
            result = self._select_job()
            if result is None:
                return None
        jid, data = result
        return Job(self, jid, data)

    @property
    def tube(self) -> str:
        return self._tube

    @property
    def direction(self) -> base.QueueDirection:
        return self._direction

    def _select_job(self) -> Optional[Tuple[int, str]]:
        with self._conn:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT rowid,jobdesc FROM jobs ORDER BY rowid LIMIT 1"
            )
            rows = [(jid, data) for jid, data in cur.fetchall()]
        if rows:
            assert len(rows) == 1
            return rows[0]
        return None

    def _insert(self, data: str) -> int:
        with self._conn:
            cur = self._conn.cursor()
            cur.execute("INSERT INTO jobs VALUES (?)", (data,))
            jid = cur.lastrowid
            cur.close()
        return jid

    def _delete(self, jid: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM jobs WHERE rowid=?", (jid,))

    def _create_jobs_table(self) -> None:
        try:
            with self._conn:
                self._conn.execute("CREATE TABLE jobs (jobdesc TEXT)")
        except sqlite3.OperationalError:
            pass

    def _connect(self) -> None:
        path = self._path
        if path.startswith('sqlite://'):
            path = path[9:]
        if path.startswith('sqlite:'):
            path = path[7:]
        self._conn = sqlite3.connect(path)
