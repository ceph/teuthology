"""
The testplan file format.

A testplan is a YAML file listing one or more suite runs::

    name: pr-smoke
    description: Fast sanity coverage for PRs
    defaults:
      limit: 20
    runs:
    - suite: rados
      subset: 1/100
      filter: [thrash]
    - suite: rbd/basic
      distro: ubuntu
      distro_version: "22.04"

Each entry in ``runs`` becomes exactly one teuthology run. Values in
``defaults`` apply to every run unless the run sets them itself. Anything tied
to a particular build or to where the plan is executed (branches, sha1s,
machine type, priority, ...) is passed on the command line instead.
"""
import dataclasses
import hashlib
import re

from dataclasses import dataclass, field
from typing import Any, ClassVar

from teuthology.orchestra.opsys import OS
from teuthology.util import yamlclass
from teuthology.util.yamlclass import Context, ValidationError

# Settings that belong to the person or system running the plan; each maps to
# the 'teuthology-testplan run' option to use instead.
COMMAND_LINE_KEYS = {
    'machine_type': '--machine-type',
    'arch': '--arch',
    'ceph': '--ceph',
    'ceph_branch': '--ceph',
    'branch': '--ceph',
    'sha1': '--sha1',
    'ceph_sha1': '--sha1',
    'ceph_repo': '--ceph-repo',
    'validate_sha1': '--validate-sha1',
    'suite_repo': '--suite-repo',
    'suite_relpath': '--suite-relpath',
    'suite_branch': '--suite-branch',
    'suite_sha1': '--suite-sha1',
    'suite_dir': '--suite-dir',
    'teuthology_branch': '--teuthology-branch',
    'kernel': '--kernel',
    'kernel_branch': '--kernel',
    'kdb': '--kdb',
    'flavor': '--flavor',
    'priority': '--priority',
    'force_priority': '--force-priority',
    'owner': '--owner',
    'email': '--email',
    'queue_backend': '--queue-backend',
    'expire': '--expire',
    'archive_upload': '--archive-upload',
    'archive_upload_url': '--archive-upload-url',
    'throttle': '--throttle',
    'job_threshold': '--job-threshold',
}

UNSUPPORTED_KEYS = (
    'num', 'timeout', 'newest', 'config_yaml', 'base_yaml_paths', 'overrides',
    'sleep_before_teardown', 'rocketchat', 'rerun', 'rerun_statuses',
)

FORBIDDEN_KEYS = {
    **{
        key: (f"{key!r} can't be set in a testplan; "
              f"pass {flag} to 'teuthology-testplan run' instead")
        for key, flag in COMMAND_LINE_KEYS.items()
    },
    **{
        key: f"{key!r} is not supported in testplans"
        for key in UNSUPPORTED_KEYS
    },
}

NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
# Labels end up in run names, where paddles splits fields on '-'. They must
# start with a letter so they can't clash with the run numbers used for
# unlabeled runs.
LABEL_RE = re.compile(r'^[A-Za-z][A-Za-z0-9._]*$')
SUBSET_RE = re.compile(r'^(\d+)/(\d+)$')


def check_name(value: str) -> str | None:
    if not NAME_RE.match(value):
        return ("must start with a letter or digit and contain only "
                "letters, digits, '.', '_' and '-'")
    return None


def check_label(value: str) -> str | None:
    if not LABEL_RE.match(value):
        return ("must start with a letter and contain only letters, "
                "digits, '.' and '_' (it becomes part of the run name)")
    return None


def check_suite(value: str) -> str | None:
    if value.startswith('/'):
        return "must be relative to the suites directory, e.g. 'rados/basic'"
    parts = re.split(r'[/:]', value.rstrip('/'))
    if not value or any(p in ('', '.', '..') for p in parts):
        return f"{value!r} is not a valid suite path"
    return None


def check_subset(value: str) -> str | None:
    match = SUBSET_RE.match(value)
    if not match:
        return f"expected 'N/M', got {value!r}"
    index, outof = (int(g) for g in match.groups())
    if not 0 <= index < outof:
        return f"expected 'N/M' with 0 <= N < M, got {value!r}"
    return None


def check_non_negative(value: int) -> str | None:
    if value < 0:
        return f"must be 0 or greater, got {value}"
    return None


def check_non_empty(value: str) -> str | None:
    if not value.strip():
        return "must not be empty"
    return None


def check_keywords(value: list[str]) -> str | None:
    if not value:
        return "must list at least one keyword"
    if any(not item.strip() for item in value):
        return "keywords must not be empty"
    return None


def known_distro_version(distro: str, version: str) -> bool:
    """Whether scheduling would accept this distro and version."""
    try:
        OS.version_codename(distro, version)
    except KeyError:
        return False
    return True


def coerce_keywords(value: Any) -> Any:
    # Same comma-separated form that teuthology-suite --filter accepts
    if isinstance(value, str):
        return [item.strip() for item in value.split(',')]
    return value


def _keywords(doc: str):
    return field(default=None, metadata={
        'coerce': coerce_keywords, 'check': check_keywords, 'doc': doc})


@dataclass(kw_only=True)
class RunSettings:
    """Settings allowed both in ``defaults`` and in each run."""
    yaml_forbidden: ClassVar[dict[str, str]] = {
        **FORBIDDEN_KEYS,
        'suite': "'suite' must be set on each run, not in defaults",
        'label': "'label' must be set on each run, not in defaults",
    }

    subset: str | None = field(default=None, metadata={
        'check': check_subset,
        'doc': "Schedule piece N of M of the suite, as 'N/M'"})
    no_nested_subset: bool | None = field(default=None, metadata={
        'doc': "Do not perform nested suite subsets"})
    seed: int | None = field(default=None, metadata={
        'check': check_non_negative,
        'doc': "Random seed; omit to pick one at scheduling time"})
    limit: int | None = field(default=None, metadata={
        'check': check_non_negative,
        'doc': "Schedule at most this many jobs; 0 means no limit"})
    filter: list[str] | None = _keywords(
        "Only run jobs whose description contains at least one keyword")
    filter_out: list[str] | None = _keywords(
        "Do not run jobs whose description contains any keyword")
    filter_all: list[str] | None = _keywords(
        "Only run jobs whose description contains every keyword")
    filter_fragments: bool | None = field(default=None, metadata={
        'doc': "Also match filters against yaml fragment contents"})
    distro: str | None = field(default=None, metadata={
        'aliases': ('os_type',), 'check': check_non_empty,
        'doc': "Distribution to run on"})
    distro_version: str | None = field(default=None, metadata={
        'aliases': ('os_version',), 'check': check_non_empty,
        'doc': "Distribution version to run on; requires distro"})


SETTING_NAMES = tuple(f.name for f in dataclasses.fields(RunSettings))


@dataclass(kw_only=True)
class RunEntry(RunSettings):
    """One suite run."""
    yaml_forbidden: ClassVar[dict[str, str]] = FORBIDDEN_KEYS

    suite: str = field(metadata={
        'check': check_suite,
        'doc': "Suite to run, e.g. 'rados' or 'rbd/basic'"})
    label: str | None = field(default=None, metadata={
        'check': check_label,
        'doc': "Short identifier for this run, unique within the plan"})


@dataclass(frozen=True)
class Source:
    """Where a resolved setting was set."""
    path: str
    line: int | None


@dataclass
class ResolvedRun:
    """A run entry with the plan defaults applied."""
    index: int
    suite: str
    label: str | None
    settings: dict[str, Any]
    sources: dict[str, Source]
    path: str
    line: int | None

    @property
    def suite_name(self) -> str:
        """The suite in the form teuthology-suite uses internally."""
        return self.suite.rstrip('/').replace('/', ':')

    @property
    def ident(self) -> str:
        return self.label or str(self.index)


@dataclass(kw_only=True)
class TestPlan:
    __test__ = False  # not a pytest test class

    yaml_forbidden: ClassVar[dict[str, str]] = FORBIDDEN_KEYS

    name: str = field(metadata={
        'check': check_name, 'doc': "Short name for the plan"})
    description: str | None = field(default=None, metadata={
        'doc': "What the plan is for"})
    defaults: RunSettings | None = field(default=None, metadata={
        'doc': "Settings applied to every run unless the run sets them"})
    runs: list[RunEntry] = field(metadata={
        'doc': "The runs to schedule; each one is a single suite"})

    # Set by load()
    filename: str | None = field(default=None, init=False, compare=False)
    sha256: str | None = field(default=None, init=False, compare=False)

    def yaml_validate(self, ctx: Context) -> None:
        if not self.runs:
            ctx.error("must list at least one run", field='runs')
            return
        labels: dict[str, int] = {}
        for i, run in enumerate(self.runs):
            if run.label is None:
                continue
            loc = yamlclass.location(run)
            line = loc.field_lines.get('label') if loc else None
            if run.label in labels:
                ctx.error(
                    f"label {run.label!r} is already used by "
                    f"runs[{labels[run.label]}]",
                    path=f"runs[{i}].label", line=line)
            else:
                labels[run.label] = i

        seen: dict[tuple, ResolvedRun] = {}
        for run in self.resolved_runs():
            if 'distro_version' in run.settings:
                source = run.sources['distro_version']
                from_defaults = source.path.startswith('defaults')
                if 'distro' not in run.settings:
                    if from_defaults:
                        ctx.error(
                            "distro_version from defaults requires distro",
                            path=run.path, line=run.line)
                    else:
                        ctx.error("distro_version requires distro (in this "
                                  "run or in defaults)",
                                  path=source.path, line=source.line)
                elif not known_distro_version(
                        run.settings['distro'],
                        run.settings['distro_version']):
                    message = (
                        f"{run.settings['distro_version']!r} is not a known "
                        f"{run.settings['distro']} version or codename")
                    if from_defaults:
                        ctx.error(f"distro_version from defaults: {message}",
                                  path=run.path, line=run.line)
                    else:
                        ctx.error(message, path=source.path,
                                  line=source.line)
            if run.label is not None:
                continue
            key = (run.suite_name, tuple(sorted(
                (k, tuple(v) if isinstance(v, list) else v)
                for k, v in run.settings.items())))
            if key in seen:
                first = seen[key]
                ctx.error(
                    f"identical to runs[{first.index}] (line {first.line}); "
                    "remove it, or give both runs a label",
                    path=run.path, line=run.line)
            else:
                seen[key] = run

    def resolved_runs(self) -> list[ResolvedRun]:
        """Apply ``defaults`` to each run."""
        defaults_loc = yamlclass.location(self.defaults)
        resolved = []
        for i, run in enumerate(self.runs):
            loc = yamlclass.location(run)
            path = f"runs[{i}]"
            settings: dict[str, Any] = {}
            sources: dict[str, Source] = {}
            for name in SETTING_NAMES:
                value = getattr(run, name)
                if value is not None:
                    settings[name] = value
                    sources[name] = Source(
                        yamlclass.join_path(
                            path, loc.field_keys.get(name, name)
                            if loc else name),
                        loc.field_lines.get(name) if loc else None)
                elif self.defaults is not None:
                    value = getattr(self.defaults, name)
                    if value is not None:
                        settings[name] = value
                        sources[name] = Source(
                            yamlclass.join_path(
                                'defaults',
                                defaults_loc.field_keys.get(name, name)
                                if defaults_loc else name),
                            defaults_loc.field_lines.get(name)
                            if defaults_loc else None)
            resolved.append(ResolvedRun(
                index=i,
                suite=run.suite,
                label=run.label,
                settings=settings,
                sources=sources,
                path=path,
                line=loc.line if loc else None,
            ))
        return resolved


def loads(text: str, filename: str | None = None) -> TestPlan:
    """
    Parse and validate a testplan.

    :raises ValidationError: listing every problem found
    """
    data, errors = yamlclass.parse(text, filename=filename)
    plan = yamlclass.from_yaml(
        TestPlan, data, filename=filename, errors=errors)
    plan.filename = filename
    plan.sha256 = hashlib.sha256(text.encode()).hexdigest()
    return plan


def load(path: str) -> TestPlan:
    """
    Read, parse and validate a testplan file.

    :raises ValidationError: listing every problem found
    """
    with open(path, 'rb') as f:
        raw = f.read()
    try:
        text = raw.decode()
    except UnicodeDecodeError as exc:
        raise ValidationError(
            [yamlclass.FieldError('', None, f"not valid UTF-8: {exc}")],
            path)
    plan = loads(text, filename=path)
    # Hash the bytes so it matches e.g. sha256sum, whatever the line endings
    plan.sha256 = hashlib.sha256(raw).hexdigest()
    return plan


__all__ = [
    'COMMAND_LINE_KEYS', 'ResolvedRun', 'RunEntry', 'RunSettings', 'Source',
    'TestPlan', 'ValidationError', 'load', 'loads',
]
