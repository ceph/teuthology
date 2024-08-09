
class LockServerMachinePool:
    def list_locks(
        self,
        ctx,
        machine_type,
        up,
        locked,
        count,
        tries=None,
    ):
        machines = query.list_locks(
            machine_type=machine_type,
            up=up,
            locked=locked,
            count=count,
            tries=tries,
        )
        return machines

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
        from teuthology.lock.ops import lock_many

        newly_locked = lock_many(
            ctx,
            requested,
            machine_type,
            ctx.owner,
            ctx.archive,
            os_type,
            os_version,
            arch,
            reimage=reimage,
        )
        return newly_locked
