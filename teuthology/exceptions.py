from typing import Optional


class BranchNotFoundError(ValueError):
    def __init__(self, branch: str, repo: Optional[str] = None) -> None:
        self.branch = branch
        self.repo = repo

    def __str__(self) -> str:
        if self.repo:
            repo_str = " in repo: %s" % self.repo
        else:
            repo_str = ""
        return "Branch '{branch}' not found{repo_str}!".format(
            branch=self.branch, repo_str=repo_str)


class BranchMismatchError(ValueError):
    def __init__(self, branch: str, repo: str, reason: Optional[str] = None) -> None:
        self.branch = branch
        self.repo = repo
        self.reason = reason

    def __str__(self) -> str:
        msg = f"Cannot use branch {self.branch} with repo {self.repo}"
        if self.reason:
            msg = f"{msg} because {self.reason}"
        return msg

class CommitNotFoundError(ValueError):
    def __init__(self, commit: str, repo: Optional[str] = None) -> None:
        self.commit = commit
        self.repo = repo

    def __str__(self) -> str:
        if self.repo:
            repo_str = " in repo: %s" % self.repo
        else:
            repo_str = ""
        return "'{commit}' not found{repo_str}!".format(
            commit=self.commit, repo_str=repo_str)


class GitError(RuntimeError):
    pass


class BootstrapError(RuntimeError):
    pass


class ConfigError(RuntimeError):
    """
    Meant to be used when an invalid config entry is found.
    """
    pass


class ParseError(Exception):
    pass


class CommandFailedError(Exception):

    """
    Exception thrown on command failure
    """
    def __init__(self, command: str, exitstatus: int, node: Optional[str] = None, label: Optional[str] = None) -> None:
        self.command = command
        self.exitstatus = exitstatus
        self.node = node
        self.label = label

    def __str__(self) -> str:
        prefix = "Command failed"
        if self.label:
            prefix += " ({label})".format(label=self.label)
        if self.node:
            prefix += " on {node}".format(node=self.node)
        return "{prefix} with status {status}: {cmd!r}".format(
            status=self.exitstatus,
            cmd=self.command,
            prefix=prefix,
            )

    def fingerprint(self) -> list[str]:
        """
        Returns a list of strings to group failures with.
        Used by sentry instead of grouping by backtrace.
        """
        return [
            self.label or self.command,
            'exit status {}'.format(self.exitstatus),
            '{{ type }}',
        ]


class AnsibleFailedError(Exception):

    """
    Exception thrown when an ansible playbook fails
    """
    def __init__(self, failures: list[str]) -> None:
        self.failures = failures

    def __str__(self) -> str:
        return "{failures}".format(
            failures=self.failures,
        )

    def fingerprint(self) -> list[str]:
        """
        Sentry will use this to group events by their failure reasons, rather
        than lumping all AnsibleFailedErrors together
        """
        return self.failures


class CommandCrashedError(Exception):

    """
    Exception thrown on crash
    """
    def __init__(self, command: str) -> None:
        self.command = command

    def __str__(self) -> str:
        return "Command crashed: {command!r}".format(
            command=self.command,
            )


class ConnectionLostError(Exception):

    """
    Exception thrown when the connection is lost
    """
    def __init__(self, command: str, node: Optional[str] = None) -> None:
        self.command = command
        self.node = node

    def __str__(self) -> str:
        node_str = 'to %s ' % self.node if self.node else ''
        return "SSH connection {node_str}was lost: {command!r}".format(
            node_str=node_str,
            command=self.command,
            )


class ScheduleFailError(RuntimeError):
    def __init__(self, message: str, name: Optional[str] = None) -> None:
        self.message = message
        self.name = name

    def __str__(self) -> str:
        return "Scheduling {name} failed: {msg}".format(
            name=self.name,
            msg=self.message,
        ).replace('  ', ' ')


class VersionNotFoundError(Exception):
    def __init__(self, url: str) -> None:
        self.url = url

    def __str__(self) -> str:
        return "Failed to fetch package version from %s" % self.url


class UnsupportedPackageTypeError(Exception):
    def __init__(self, node) -> None:
        self.node = node

    def __str__(self) -> str:
        return "os.package_type {pkg_type!r} on {node}".format(
            node=self.node, pkg_type=self.node.os.package_type)


class SELinuxError(Exception):
    def __init__(self, node, denials: list[str]) -> None:
        self.node = node
        self.denials = denials

    def __str__(self) -> str:
        return "SELinux denials found on {node}: {denials}".format(
            node=self.node, denials=self.denials)


class QuotaExceededError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message

    def __str__(self) -> str:
        return self.message


class SkipJob(Exception):
    """
    Used by teuthology.worker when it notices that a job is broken and should
    be skipped.
    """
    pass


class MaxWhileTries(Exception):
    pass


class ConsoleError(Exception):
    pass


class NoRemoteError(Exception):
    message = "This operation requires a remote"

    def __str__(self) -> str:
        return self.message


class UnitTestError(Exception):
    """
    Exception thrown on unit test failure
    """
    def __init__(self, exitstatus: Optional[int] = None, node: Optional[str] = None, label: Optional[str] = None, message: Optional[str] = None) -> None:
        self.exitstatus = exitstatus
        self.node = node
        self.label = label
        self.message = message

    def __str__(self) -> str:
        prefix = "Unit test failed"
        if self.label:
            prefix += " ({label})".format(label=self.label)
        if self.node:
            prefix += " on {node}".format(node=self.node)
        if self.exitstatus:
            prefix += " with status {status}".format(status=self.exitstatus)
        return "{prefix}: '{message}'".format(
            prefix=prefix,
            message=self.message,
        )
