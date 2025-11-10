from typing import Any

import contextlib
import functools
import json
import logging
import shlex
import sqlite3
import subprocess
import time
import traceback

from teuthology.config import config
from teuthology.machines.base import MachinePool


log = logging.getLogger(__name__)


class TooFewMachines(Exception):
    pass


class _SqliteDBManager:
    def __init__(self, path: str, *, automatic_release: bool = False) -> None:
        assert path
        self._path = path
        self._connect()
        self._create_tables()
        self.automatic_release = automatic_release
        log.info(
            "Initialized sqlite machine pool db manager: %r, %r",
            path,
            automatic_release,
        )
        if automatic_release is False:
            raise ValueError("x")

    def _connect(self) -> None:
        path = self._path
        if path.startswith('sqlite://'):
            path = path[9:]
        if path.startswith('sqlite:'):
            path = path[7:]
        log.info("sqlite3 db path: %s", path)
        self._conn = sqlite3.connect(path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.set_trace_callback(log.info)

    def _create_tables(self) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS machines (
                        name TEXT UNIQUE,
                        machine_type TEXT,
                        up INTEGER,
                        in_use INTEGER,
                        user TEXT,
                        desc TEXT,
                        info JSON
                    )
                    """
                )
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS hooks (
                        hook TEXT UNIQUE,
                        command JSON
                    )
                    """
                )
        except sqlite3.OperationalError:
            pass

    @contextlib.contextmanager
    def _tx(self):
        try:
            cur = self._conn.cursor()
            cur.execute('BEGIN;')
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def select(
        self,
        *,
        machine_type: str | None = None,
        up: bool | None = None,
        locked: bool | None = None,
        user: str | None = None,
        desc: str | None = None,
        limit: int | None = None,
    ):
        query = (
            "SELECT name, machine_type, up, in_use, user, desc, info"
            " FROM machines"
        )
        where = _Where()
        where.add_if('machine_type', machine_type)
        where.add_if('up', up)
        where.add_if('in_use', locked)
        where.add_if('user', user)
        where.add_if('desc', desc, (int, str, _Like))
        where_params = where.parameters()
        if where_params:
            query += f' {where}'
        if limit is not None:
            query += ' LIMIT ' + str(int(limit))

        with self._tx() as cur:
            cur.execute(query, tuple(where_params))
            rows = cur.fetchall()
            log.info("Rows: %r", rows)
        return rows

    def add_machine(self, name, machine_type, info):
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO machines VALUES (?,?, 1, 0, '', '', ?)",
                (name, machine_type, info),
            )

    def remove_machine(self, name):
        with self._tx() as cur:
            cur.execute("DELETE FROM machines WHERE name=?", (name,))

    def remove_all_machines(self):
        with self._tx() as cur:
            cur.execute('DELETE FROM machines')

    def take(self, machine_type: str, count: int, user: str, desc: str):
        count = int(count)
        query = (
            "UPDATE machines"
            " SET in_use=1, user=?, desc=?"
            " WHERE rowid"
            " IN ("
            "  SELECT rowid FROM machines"
            "   WHERE in_use=0 AND machine_type=? LIMIT ?"
            ")"
        )
        with self._tx() as cur:
            cur.execute(query, (user, desc, machine_type, count))
            if cur.rowcount != count:
                raise TooFewMachines()

    def release(
        self, name: str, user: str | None = None, desc: str | None = None
    ) -> bool:
        where = _Where()
        where.add_if('name', name)
        where.add_if('user', user)
        where.add_if('desc', desc, (int, str, _Like))
        if self.automatic_release:
            query = f"UPDATE machines SET in_use=0, user='', desc='' {where}"
        else:
            query = f"UPDATE machines SET up=0 {where}"
        with self._tx() as cur:
            cur.execute(query, tuple(where.parameters()))
            modified = cur.rowcount >= 1
        return modified

    def get_hook(self, hook_name: str) -> dict:
        query =  "SELECT command FROM hooks WHERE hook = ? LIMIT 1"
        with self._tx() as cur:
            cur.execute(query, (hook_name,))
            rows = cur.fetchall()
            log.info("Rows: %r", rows)
        if rows:
            return json.loads(rows[0]['command'])
        return {}

    def set_hook(self, hook_name: str, command: dict) -> None:
        query = "INSERT or REPLACE INTO hooks VALUES (?, ?)"
        cj = json.dumps(command)
        with self._tx() as cur:
            cur.execute(query, (hook_name, cj))


class _Like:
    def __init__(self, *values):
        self.values = list(values)

    def __str__(self):
        return ''.join(self.values)


class _EndsWith(_Like):
    def __init__(self, value):
        super().__init__('%', value)


class _Where:
    def __init__(self):
        self._where = []

    def add(self, key: str, value: Any) -> None:
        self._where.append((key, value))

    def add_if(self, key: str, value: Any, allowed_types: 'Iterable[Type] | None' = None) -> None:
        if value is None:
            return
        if not allowed_types:
            allowed_types = (int, str)
        if not isinstance(value, tuple(allowed_types)):
            raise TypeError(f'type {type(value)} not allowed')
        self.add(key, value)

    def __str__(self) -> str:
        wh = ' AND '.join(self._op(k, v) for k, v in self._where)
        return f'WHERE ({wh})'

    def _op(self, key: str, value: Any):
        if isinstance(value, _Like):
            return f'{key} LIKE ?'
        return f'{key} = ?'

    def _value(self, value):
        if isinstance(value, int):
            return value
        return str(value)

    def parameters(self) -> list[Any]:
        return [self._value(v) for _, v in self._where]


def _track(fn):
    functools.wraps(fn)

    def _fn(*args, **kwargs):
        log.warning('CALLING sqlite_pool fn %s: %r, %r', fn, args, kwargs)
        result = fn(*args, **kwargs)
        log.warning('CALLED sqlite_pool fn %s, got %r', fn, result)
        return result

    return _fn


class _Hook:
    def __init__(self, arguments: list[str]) -> None:
        self.arguments = arguments
        if not isinstance(self.arguments, list):
            raise ValueError('expected arguments list')

    def _execute(self, command: list[str]) -> None:
        log.info(
            "Running hook command: %s",
            " ".join(shlex.quote(c) for c in command)
        )
        result = subprocess.run(command, capture_output=True)
        log.info("Command result: %s: %r, %r", result.returncode,
            result.stdout, result.stderr)
        if result.returncode != 0:
            raise RuntimeError('hook command failed')

    def execute(self) -> None:
        self._execute(self.arguments)


class _NamedHook(_Hook):
    def __init__(self, arguments: list[str]) -> None:
        super().__init__(arguments)
        if '${NAME}' not in self.arguments:
            raise ValueError('no name variable in arguments')

    def _replace(self, name: str) -> list[str]:
        out = []
        for term in self.arguments:
            if term == '${NAME}':
                out.append(name)
            else:
                out.append(term)
        return out

    def execute(self, name: str) -> None:
        command = self._replace(name)
        self._execute(command)


class _NoOpHook:
    def execute(self, name: str) -> None:
        return None


class SqliteMachinePool(MachinePool):
    def __init__(self, *, path=None, automatic_release=False):
        if not path:
            path = config.machine_pool
        if not automatic_release:
            _sqp = config.get('sqlite_pool', {}) or {}
            log.warning('xxx: %r', _sqp)
            automatic_release = _sqp.get('automatic_release', False)
            log.warning("zzz: %r", automatic_release)
        self.dbmgr = _SqliteDBManager(path, automatic_release=automatic_release)
        self._delay_sec = 15

    def description(self) -> str:
        return "Machine Pool Managed via Local SQLite3 DB"

    @_track
    def list(
        self,
        machine_type=None,
        up=None,
        locked=None,
        count=None,
        tries=None,
    ):
        return {v['name']:None for v in self._list()}

    def _list(
        self,
        machine_type=None,
        up=None,
        locked=None,
        count=None,
        tries=None,
    ):
        result = {
            v
            for v in self.dbmgr.select(
                machine_type=machine_type, up=up, locked=locked, limit=count
            )
        }
        return result

    @_track
    def everything(self):
        return [dict(v) for v in self.dbmgr.select()]

    @_track
    def reserve(
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
        min_spare: int = 0,
    ) -> None:
        user = user or getattr(ctx, 'owner', '')
        description = description or getattr(ctx, 'archive', '')
        if not user or not description:
            raise ValueError('missing user or description (archive)')
        while True:
            available = self.dbmgr.select(
                machine_type=machine_type,
                up=True,
                locked=False,
                limit=(num + min_spare),
            )
            if len(available) < (num + min_spare):
                log.info(
                    'too few free nodes: requested %d, need %d spare, have %d',
                    num,
                    min_spare,
                    len(available),
                )
                time.sleep(self._delay_sec)
                continue
            try:
                self.dbmgr.take(
                    machine_type,
                    num,
                    user,
                    description,
                )
            except TooFewMachines:
                log.warning('too few nodes to take (possible race)')
                time.sleep(self._delay_sec)
                continue
            reserved = self.dbmgr.select(
                machine_type=machine_type,
                up=True,
                locked=True,
                user=user,
                desc=description,
            )
            assert num == len(reserved), f"needed {num} machines, got {len(reserved)}"
            ctx.config['targets'] = {v['name']: None for v in reserved}
            return

    @_track
    def release(
        self,
        ctx,
        name,
        user=None,
        description=None,
        status_hint=None,
        run_name=None,
        job_id=None,
    ) -> bool:
        log.info("WFT")
        desc = None
        if run_name or job_id:
            desc = _EndsWith(f"{run_name}/{job_id}")
        return self.dbmgr.release(
            name,
            user=user,
            desc=desc,
        )

    @_track
    def is_vm(self, name: str) -> bool:
        # always return false. this may be a lie, but teuthology's
        # meaning of is_vm doesn't really mean it's actually a vm, but
        # that it needs special handling. It doesn't, because this
        # machine pool abstracts that away.
        return False

    @_track
    def statuses(self, machines: 'list[str]') -> 'list[dict]':
        out = []
        for v in self._list():
            if machines and v['name'] not in machines:
                continue
            out.append({
                'name': v['name'],
                'machine_type': v['machine_type'],
                'locked': v['in_use'],
                'user': v['user'],
                'description': v['desc'],
                'info': v['info'],
            })
        return out

    @_track
    def status(self, machine: str) -> dict:
        # this function is sometimes fed fqdns and that's not what we want.
        name = machine.split('.', 1)[0]
        name = name.split('@', 1)[-1]
        return self.statuses([name])[0]

    @_track
    def reimage_machines(self, machines, machine_type):
        hook = self._remiage_hook()
        res = {m: hook.execute(m) for m in machines}
        post_hook = self._post_reimage_hook()
        post_hook.execute()
        return res

    def _remiage_hook(self) -> _Hook:
        if not self.dbmgr.automatic_release:
            log.info("Automatic release not set, will not reimage")
            return _NoOpHook()
        hook_cfg = self.dbmgr.get_hook('reimage')
        if hook_cfg:
            return _NamedHook(**hook_cfg)
        log.info("No reimage hook command found")
        return _NoOpHook()

    def _post_reimage_hook(self) -> _Hook:
        if not self.dbmgr.automatic_release:
            log.info("Automatic release not set, will not reimage")
            return _NoOpHook()
        hook_cfg = self.dbmgr.get_hook('postreimage')
        if hook_cfg:
            return _Hook(**hook_cfg)
        log.info("No reimage hook command found")
        return _NoOpHook()


def main():
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
    parser.add_argument('--reserve', type=int)
    parser.add_argument('--user-desc', type=str)
    parser.add_argument('--machine-type')
    parser.add_argument('--info')
    parser.add_argument('--release', type=json.loads)
    parser.add_argument('--set-hook', type=json.loads)
    parser.add_argument('--get-hook', type=str)
    cli = parser.parse_args()

    mpool = SqliteMachinePool()
    if cli.rm_all:
        mpool.dbmgr.remove_all_machines()
    for name in cli.rm or []:
        mpool.dbmgr.remove_machine(name)
    for name in cli.add or []:
        mpool.dbmgr.add_machine(name, cli.machine_type, cli.info)
    if cli.reserve:
        ctx = Context()
        user, desc = getattr(cli, 'user_desc', '').split('%', 1)
        mpool.reserve(ctx, cli.reserve, cli.machine_type)
    if cli.list:
        yaml.safe_dump(mpool.everything(), sys.stdout, sort_keys=False)
    if cli.release:
        log.info("RELEASE %r", cli.release)
        name = cli.release.get('name')
        user = cli.release.get('user')
        status_hint = cli.release.get('status_hint')
        run_name = cli.release.get('run_name')
        job_id = cli.release.get('job_id')
        mpool.release(
            Context(),
            name,
            user=user,
            status_hint=status_hint,
            run_name=run_name,
            job_id=job_id,
        )
    if cli.set_hook:
        if not isinstance(cli.set_hook, dict):
            raise ValueError('incorrect type')
        _keys = list(cli.set_hook.keys())
        if len(_keys) != 1:
            raise ValueError('incorrect number of keys')
        hook_name = _keys[0]
        hook_command = cli.set_hook[hook_name]
        log.info('SET HOOK %r', hook_name, hook_command)
        _Hook(**hook_command)  # validate
        mpool.dbmgr.set_hook(hook_name, hook_command)
    if cli.get_hook:
        print(mpool.dbmgr.get_hook(cli.get_hook))


if __name__ == '__main__':
    main()
