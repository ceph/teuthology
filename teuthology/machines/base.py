import abc


class MachinePool(abc.ABC):
    @abc.abstractmethod
    def description(self) -> str: ...

    @abc.abstractmethod
    def list(
        self,
        machine_type: str | None = None,
        up: bool | None = None,
        locked: bool | None = None,
        count: int | None = None,
        tries: int | None = None,
    ): ...

    @abc.abstractmethod
    def reserve(
        self,
        ctx: Any,
        num: int,
        machine_type: str,
        user: str | None = None,
        description: str | None = None,
        os_type: str | None = None,
        os_version: str | None = None,
        arch: str | None = None,
        reimage: bool = True,
    ): ...

    @abc.abstractmethod
    def release(
        self,
        ctx: Any,
        name: str,
        user: str | None = None,
        description: str | None = None,
        status_hint: str | None = None,
        constraints: str | None = None,
    ) -> bool: ...

    @abc.abstractmethod
    def is_vm(self, name: str) -> bool: ...

    @abc.abstractmethod
    def statuses(self, name: list[str]) -> list[dict]: ...


class ExtendedMachinePool(MachinePool, abc.ABC):
    """For testing and verification of optional machine pool methods."""

    @abc.abstractmethod
    def reimage_machines(
        self, ctx: Any, machines: list[str], machine_type: str
    ) -> list[str]: ...

    @abc.abstractmethod
    def update_lock(
        self,
        name: str,
        description: str | None = None,
        status: str | None = None,
        ssh_pub_key: str | None = None,
    ): ...

    @abc.abstractmethod
    def status(self, machine: str) -> dict: ...
