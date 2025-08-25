from teuthology.config import config
from teuthology.machines.base import MachinePool
from teuthology.machines.pool import auto_pool


def _temp_context():
    return None


def must_reserve(
    ctx,
    num: int,
    machine_type: str,
    reimage: bool = True,
    tries = None,
    *,
    machine_pool: MachinePool | None = None,
) -> None:
    os_type = ctx.config.get("os_type")
    os_version = ctx.config.get("os_version")
    arch = ctx.config.get("arch")
    reserved = config.reserve_machines
    assert isinstance(reserved, int), "reserve_machines must be integer"
    assert reserved >= 0, "reserve_machines should >= 0"

    return auto_pool(pool=machine_pool).reserve(
        ctx,
        num=num,
        min_spare=reserved,
        machine_type=machine_type,
        user=ctx.owner,
        description=ctx.archive,
        os_type=os_type,
        os_version=os_version,
        arch=arch,
        reimage=reimage,
    )


def unlock_one(
    name: str,
    user: str,
    description: str | None = None,
    status: dict | None = None,
    *,
    machine_pool: MachinePool | None = None,
) -> bool:
    return auto_pool(pool=machine_pool).release(
        _temp_context(),
        name=name,
        user=user,
        description=description,
        status_hint=status,
    )


def unlock_safe(
    names: list[str],
    owner: str,
    run_name: str = "",
    job_id: str = "",
    *,
    machine_pool: MachinePool | None = None,
) -> bool:
    pool = auto_pool(pool=machine_pool)

    def _unlock(name: str) -> bool:
        return pool.release(
            _temp_context(),
            name=name,
            user=owner,
            run_name=run_name,
            job_id=job_id,
        )

    # Does this NEED to be parallel? It is in the original version.
    return all(_unlock(name) for name in names)


def find_stale_locks(
    owner=None, *, machine_pool: MachinePool | None = None
) -> list[dict]:
    pool = auto_pool(pool=machine_pool)
    return pool.list(stale=True, owner=owner)


def reimage_machines(
    ctx, machines, machine_type, *, machine_pool: MachinePool | None = None
):
    pool = auto_pool(pool=machine_pool)
    reimage_machines_fn = getattr(pool, 'reimage_machines', None)
    if reimage_machines_fn is None:
        raise NotImplementedError("pool does not support reimage_machines")
    return reimage_machines_fn(machines, machine_type)


def update_lock(
    name,
    description=None,
    status=None,
    ssh_pub_key=None,
    *,
    machine_pool: MachinePool | None = None,
) -> bool:
    pool = auto_pool(pool=machine_pool)
    update_lock_fn = getattr(pool, 'update_lock', None)
    if update_lock_fn is None:
        raise NotImplementedError("pool does not support update_lock")
    return update_lock_fn(name, description, status, ssh_pub_key)


def is_vm(
    name: str,
    *,
    machine_pool: MachinePool | None = None,
) -> bool:
    return auto_pool(pool=machine_pool).is_vm(name)


def machine_status(
    name: str,
    *,
    machine_pool: MachinePool | None = None,
):
    pool = auto_pool(pool=machine_pool)
    machine_status_fn = getattr(pool, 'status', None)
    if machine_status_fn is not None:
        return machine_status_fn(name)
    # fall back to getting one machine from statuses
    return pool.statuses([name])[0]


def machine_statuses(
    names,
    *,
    machine_pool: MachinePool | None = None,
):
    pool = auto_pool(pool=machine_pool)
    return pool.statuses(names)


def machine_list(
    machine_type: str|None = None,
    count: int|None = None,
    tries: int|None = None,
    *,
    machine_pool: MachinePool | None = None,
) -> bool:
    # same as machine_statuses? 
    pool = auto_pool(pool=machine_pool)
    return pool.list(machine_type=machine_type, count=count, tries=tries)
