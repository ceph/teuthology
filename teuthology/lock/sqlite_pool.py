import logging
import sqlite3


log = logging.getLogger(__name__)


class SqliteMachinePool:
    def __init__(
        self, path: str,
    ) -> None:
        self._path = path
        self._connect()
        self._create_tables()

    def _select_machines(self, ):
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

    def _delete(self, jid: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM jobs WHERE rowid=?", (jid,))

    def _create_tables(self) -> None:
        try:
            with self._conn:
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS machines (
                        name TEXT,
                        mtype TEXT,
                        up INTEGER,
                        in_use INTEGER,
                        info JSON
                    )
                """)
        except sqlite3.OperationalError:
            pass

    def _select(self, machine_type, up, locked, count):
        query = "SELECT name, mtype, up, in_use, info FROM machines"
        where = []
        params = []
        if machine_type is not None:
            where.append('mtype=?')
            params.append(machine_type)
        if up is not None:
            where.append('up=?')
            params.append(1 if up else 0)
        if locked is not None:
            where.append('in_use=?')
            params.append(1 if locked else 0)
        if where:
            query += ' WHERE ' + (' AND '.join(where))
        if count is not None:
            query += ' LIMIT '+ str(int(count))

        with self._conn:
            cur = self._conn.cursor()
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
            log.info("Rows: %r", rows)
        return rows

    def add_machine(self, name, machine_type, info):
        with self._conn:
            cur = self._conn.cursor()
            cur.execute("INSERT INTO machines VALUES (?,?, 1, 0, ?)", (name, machine_type,info))
            cur.close()

    def remove_machine(self, name):
        with self._conn:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM machines WHERE name=?", (name,))
            cur.close()

    def _take(self, machine_type, count):
        count = int(count)
        query = "UPDATE machines SET in_use=1 WHERE rowid IN (SELECT rowid FROM machines WHERE in_use=0 AND mtype=? LIMIT ?)"
        with self._conn:
            cur = self._conn.cursor()
            cur.execute(query, (machine_type, count))
            cur.close()

    def _connect(self) -> None:
        path = self._path
        if path.startswith('sqlite://'):
            path = path[9:]
        if path.startswith('sqlite:'):
            path = path[7:]
        log.warning("P:%s", path)
        self._conn = sqlite3.connect(path)

    def everything(self):
        return self._select(None, None, None, None)

    def list_locks(
        self,
        ctx,
        machine_type,
        up,
        locked,
        count,
        tries=None,
    ):
        return {v[0]: None for v in self._select(machine_type, up, locked, count)}

    def acquire(
        self,
        ctx,
        num,
        machine_type,
        user=None,
        description=None,
        os_type=None,
        os_version=None,
        arch=None,
        reimage=True,
    ):
        self._take(machine_type, num)
        return {v[0]: None for v in self._select(machine_type, True, True, num)}

    def is_vm(self, name):
        return False


def main():
    from teuthology.config import config
    import argparse
    import sys
    import yaml

    parser = argparse.ArgumentParser()
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--add', action='append')
    parser.add_argument('--rm', action='append')
    parser.add_argument('--acquire', type=int)
    parser.add_argument('--machine-type')
    parser.add_argument('--info')
    cli = parser.parse_args()

    mpool = SqliteMachinePool(config.machine_pool)
    for name in cli.rm or []:
        mpool.remove_machine(name)
    for name in cli.add or []:
        mpool.add_machine(name, cli.machine_type, cli.info)
    if cli.acquire:
        mpool.acquire(None, cli.acquire, cli.machine_type)
    if cli.list:
        yaml.safe_dump(mpool.everything(), sys.stdout)


if __name__ == '__main__':
    main()
