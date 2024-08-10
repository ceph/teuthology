import logging
import sqlite3


log = logging.getLogger(__name__)


class SqliteMachinePool:
    def __init__(
        self,
        path: str,
    ) -> None:
        self._path = path
        self._connect()
        self._create_tables()

    def _create_tables(self) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS machines (
                        name TEXT UNIQUE,
                        mtype TEXT,
                        up INTEGER,
                        in_use INTEGER,
                        cookie TEXT,
                        info JSON
                    )
                    """
                )
        except sqlite3.OperationalError:
            pass

    def _select(
        self,
        *,
        machine_type=None,
        up=None,
        locked=None,
        cookie=None,
        count=None,
    ):
        query = "SELECT name, mtype, up, in_use, cookie, info FROM machines"
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
        if cookie is not None:
            where.append('cookie=?')
            params.append(cookie)
        if where:
            query += ' WHERE ' + (' AND '.join(where))
        if count is not None:
            query += ' LIMIT ' + str(int(count))

        with self._conn:
            self._conn.row_factory = sqlite3.Row
            cur = self._conn.cursor()
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
            log.info("Rows: %r", rows)
        return rows

    def add_machine(self, name, machine_type, info):
        with self._conn:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO machines VALUES (?,?, 1, 0, '', ?)",
                (name, machine_type, info),
            )
            cur.close()

    def remove_machine(self, name):
        with self._conn:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM machines WHERE name=?", (name,))
            cur.close()

    def remove_all_machines(self):
        with self._conn:
            cur = self._conn.cursor()
            cur.execute('DELETE FROM machines')
            cur.close()

    def _take(self, machine_type, count, cookie):
        count = int(count)
        query = "UPDATE machines SET in_use=1, cookie=? WHERE rowid IN (SELECT rowid FROM machines WHERE in_use=0 AND mtype=? LIMIT ?)"
        with self._conn:
            cur = self._conn.cursor()
            cur.execute(query, (cookie, machine_type, count))
            cur.close()

    def _connect(self) -> None:
        path = self._path
        if path.startswith('sqlite://'):
            path = path[9:]
        if path.startswith('sqlite:'):
            path = path[7:]
        log.warning("P:%s", path)
        self._conn = sqlite3.connect(path)
        # self._conn.set_trace_callback(print)

    def everything(self):
        return [dict(v) for v in self._select()]

    def list_locks(
        self,
        ctx,
        machine_type,
        up,
        locked,
        count,
        tries=None,
    ):
        return {
            v[0]: None
            for v in self._select(
                machine_type=machine_type, up=up, locked=locked, count=count
            )
        }

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
        cookie = getattr(ctx, 'job_cookie', None)
        if cookie is None:
            user = user or 'default'
            description = description or 'missing'
            cookie = f'{user}/{description}'
            if ctx:
                setattr(ctx, 'job_cookie', cookie)

        self._take(machine_type, num, cookie)
        return {
            v[0]: None
            for v in self._select(
                machine_type=machine_type,
                up=True,
                locked=True,
                count=num,
                cookie=cookie,
            )
        }

    def is_vm(self, name):
        return False


def main():
    from teuthology.config import config
    import argparse
    import sys
    import yaml

    class Context:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--add', action='append')
    parser.add_argument('--rm-all', action='store_true')
    parser.add_argument('--rm', action='append')
    parser.add_argument('--acquire', type=int)
    parser.add_argument('--cookie', type=str)
    parser.add_argument('--machine-type')
    parser.add_argument('--info')
    cli = parser.parse_args()

    mpool = SqliteMachinePool(config.machine_pool)
    if cli.rm_all:
        mpool.remove_all_machines()
    for name in cli.rm or []:
        mpool.remove_machine(name)
    for name in cli.add or []:
        mpool.add_machine(name, cli.machine_type, cli.info)
    if cli.acquire:
        ctx = Context()
        setattr(ctx, 'job_cookie', cli.cookie)
        mpool.acquire(ctx, cli.acquire, cli.machine_type)
    if cli.list:
        yaml.safe_dump(mpool.everything(), sys.stdout, sort_keys=False)


if __name__ == '__main__':
    main()
