
from teuthology.machines.base import MachinePool
from teuthology.lock import query, ops


class LockServerMachinePool(MachinePool):
    def description(self) -> str:
        return "Locks Physical Lab Machines via API"

    def list(
        self,
        machine_type=None,
        up=None,
        locked=None,
        count=None,
        tries=None,
    ):
        kwargs = {}
        if machine_type is not None:
            kwargs['machine_type'] = machine_type
        if up is not None:
            kwargs['up'] = up
        if locked is not None:
            kwargs['locked'] = locked
        if count is not None:
            kwargs['count'] = count
        if tries is not None:
            kwargs['tries'] = tries
        return query.list_locks(**kwargs)

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
        min_spare=None,
    ):
        return ops.lock_many(
            ctx,
            num,
            machine_type=machine_type,
            user=ctx.owner,
            description=ctx.archive,
            os_type=os_type,
            os_version=os_version,
            arch=arch,
            reimage=reimage,
        )

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
        if job_id or run_name:
            assert (
                not description
            ), "description not supported with job_id/run_name"
            assert (
                not status_hint
            ), "status_hint not supported with job_id/run_name"
            return ops.unlock_one_safe(
                name=name,
                owner=user,
                run_name=run_name,
                job_id=job_id,
            )
        return ops.unlock_one(
            name=name,
            user=user,
            description=description,
            status=status_hint,
        )

    def is_vm(self, name: str) -> bool:
        return query.is_vm(name)

    def statuses(self, machines: 'list[str]') -> 'list[dict]':
        return query.get_statuses(name)

    def update_lock(
        self, name, description=None, status=None, ssh_pub_key=None
    ):
        return ops.update_lock(
            name,
            description=description,
            status=status,
            ssh_pub_key=ssh_pub_key,
        )
