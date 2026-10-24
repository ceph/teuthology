"""
Schedule and inspect testplans: bundles of suite runs defined in a YAML file.
See teuthology.testplan.plan for the file format.
"""
import collections
import datetime
import logging
import os
import random
import sys

import teuthology
from teuthology.config import config, JobConfig
from teuthology.orchestra.opsys import OS
from teuthology.suite import apply_common_args, process_args, wait
from teuthology.suite import util as suite_util
from teuthology.suite.build_matrix import build_matrix
from teuthology.suite.merge import config_merge
from teuthology.suite.run import Run
from teuthology.testplan.plan import (
    NAME_RE, ResolvedRun, TestPlan, ValidationError, load,
)
from teuthology.util import yamlclass
from teuthology.util.time import TIMESTAMP_FMT
from teuthology.util.yamlclass import FieldError

log = logging.getLogger(__name__)

TESTPLANS_DIR = 'testplans'

# teuthology-suite options that testplans set per run, or that
# teuthology-testplan does not offer. Values are in teuthology-suite's
# command-line form, as expected by process_args().
SUITE_ARG_DEFAULTS = {
    '--suite': None,
    # --newest backtracks separately for each run, which would let runs of
    # one plan test different builds
    '--newest': '0',
    '--rerun': None,
    '--rerun-statuses': 'fail,dead',
    '--seed': '-1',
    '--subset': None,
    '--no-nested-subset': False,
    '--limit': '0',
    '--num': '1',
    '--filter': None,
    '--filter-out': None,
    '--filter-all': None,
    '--filter-fragments': 'false',
    '--distro': None,
    '--distro-version': None,
    '--timeout': None,
    '--sleep-before-teardown': '0',
    '--rocketchat': None,
    '<config_yaml>': [],
}

# teuthology-testplan options that are not teuthology-suite options
TESTPLAN_ONLY_ARGS = (
    '--help', '--jobs', '--strict', '<testplan>',
    'run', 'show', 'list', 'validate',
)


class TestplanError(Exception):
    """A problem that prevents a command from running."""
    __test__ = False  # not a pytest test class


def main(args):
    if args['--verbose']:
        teuthology.log.setLevel(logging.DEBUG)
    try:
        if args['run']:
            return cmd_run(args)
        if args['show']:
            return cmd_show(args)
        if args['list']:
            return cmd_list(args)
        if args['validate']:
            return cmd_validate(args)
    except (TestplanError, ValidationError) as exc:
        print(exc, file=sys.stderr)
        return 1
    raise AssertionError(f"no command in {args!r}")


def suite_args(args) -> dict:
    """Translate teuthology-testplan options to teuthology-suite ones."""
    result = dict(SUITE_ARG_DEFAULTS)
    result.update({
        key: value for key, value in args.items()
        if key not in TESTPLAN_ONLY_ARGS
    })
    return result


class SuiteCheckout(Run):
    """
    Choose and fetch the suite repo the same way a Run does, without building
    a run. Used to find testplans by name and to check them before any run
    is created.
    """
    def __init__(self, args):
        self.args = args
        self.name = 'testplan'
        self.suite_branch = None
        self.suite_hash = None
        if args.suite_dir:
            self.suite_repo_path = args.suite_dir
            return
        if args.ceph_repo:
            config.ceph_git_url = args.ceph_repo
        if args.suite_repo:
            config.ceph_qa_suite_git_url = args.suite_repo
        self.suite_branch = self.choose_suite_branch()
        self.suite_hash = self.choose_suite_hash(self.suite_branch)
        self.suite_repo_path = suite_util.fetch_repos(
            self.suite_branch, test_name=self.name,
            dry_run=args.dry_run, commit=self.suite_hash)


def testplans_dir(suite_repo_path: str, suite_relpath: str) -> str:
    return os.path.join(suite_repo_path, suite_relpath or '', TESTPLANS_DIR)


def suites_dir(suite_repo_path: str, suite_relpath: str) -> str:
    return os.path.join(suite_repo_path, suite_relpath or '', 'suites')


def is_plan_name(ref: str) -> bool:
    return not (ref.endswith('.yaml') or ref.endswith('.yml') or
                '/' in ref or os.sep in ref)


def plan_path(ref: str, plans_dir: str | None) -> str:
    """
    Turn a testplan reference into a file path.

    :param plans_dir: Where to look up plans by name; None if unavailable
    """
    if ref.endswith('.yml'):
        raise TestplanError(
            f"{ref}: testplan files must use the .yaml extension")
    if not is_plan_name(ref):
        if not os.path.isfile(ref):
            raise TestplanError(f"{ref}: no such file")
        return ref
    if not NAME_RE.match(ref):
        raise TestplanError(f"{ref!r} is not a valid testplan name")
    if plans_dir is None:
        raise TestplanError(
            f"{ref!r} looks like a testplan name; pass --suite-dir to look "
            "it up, or give the path to the file")
    path = os.path.join(plans_dir, ref + '.yaml')
    if not os.path.isfile(path):
        available = ', '.join(available_plans(plans_dir)) or 'none'
        raise TestplanError(
            f"no testplan named {ref!r} in {plans_dir} (available: "
            f"{available})")
    return path


def available_plans(plans_dir: str) -> list[str]:
    if not os.path.isdir(plans_dir):
        return []
    return sorted(
        name[:-len('.yaml')] for name in os.listdir(plans_dir)
        if name.endswith('.yaml')
    )


def suite_path(suites_root: str, run: ResolvedRun) -> str:
    return os.path.normpath(
        os.path.join(suites_root, run.suite_name.replace(':', '/')))


def check_suites(plan: TestPlan, suites_root: str) -> None:
    """
    Check that every suite named by the plan exists.

    :raises ValidationError: listing each missing suite
    """
    errors = []
    for run in plan.resolved_runs():
        if not os.path.exists(suite_path(suites_root, run)):
            loc = yamlclass.location(plan.runs[run.index])
            line = loc.field_lines.get('suite') if loc else run.line
            errors.append(FieldError(
                f"{run.path}.suite", line,
                f"suite {run.suite!r} not found in {suites_root}"))
    if errors:
        raise ValidationError(errors, plan.filename)


def count_jobs(run: ResolvedRun, suites_root: str) -> int:
    """
    Count the jobs a run would schedule. This builds and filters the suite
    like teuthology-suite does, but cannot account for packages that are
    missing or for jobs excluded by arch or os_type at scheduling time.
    """
    settings = run.settings
    subset = settings.get('subset')
    if subset:
        subset = tuple(int(i) for i in subset.split('/'))
    seed = settings.get('seed', 0)
    configs = build_matrix(
        suite_path(suites_root, run),
        subset=subset,
        no_nested_subset=settings.get('no_nested_subset', False),
        seed=seed,
    )
    base_config = {}
    if 'distro' in settings:
        base_config['os_type'] = settings['distro'].lower()
    if 'distro_version' in settings:
        # As Run.create_initial_config() does
        version, _ = OS.version_codename(
            settings['distro'], settings['distro_version'])
        base_config['os_version'] = version.lower()
    count = sum(1 for _ in config_merge(
        configs,
        base_config=JobConfig.from_dict(base_config),
        filter_in=settings.get('filter', []),
        filter_out=settings.get('filter_out', []),
        filter_all=settings.get('filter_all', []),
        filter_fragments=settings.get('filter_fragments', False),
        seed=seed,
        suite_name=run.suite_name,
    ))
    limit = settings.get('limit', 0)
    if limit:
        count = min(count, limit)
    return count


def count_all_jobs(plan: TestPlan, suites_root: str) -> dict[int, int]:
    """
    Count the jobs for every run in the plan.

    :returns: {run index: job count}
    :raises ValidationError: for runs whose suite could not be built
    """
    counts = {}
    errors = []
    for run in plan.resolved_runs():
        try:
            counts[run.index] = count_jobs(run, suites_root)
        except Exception as exc:
            log.debug("Counting jobs for %s failed", run.path, exc_info=True)
            errors.append(FieldError(
                run.path, run.line,
                f"could not build suite {run.suite!r}: "
                f"{type(exc).__name__}: {exc}"))
    if errors:
        raise ValidationError(errors, plan.filename)
    return counts


def name_suffixes(plan: TestPlan) -> dict[int, str | None]:
    """
    Pick the run name suffix for each run. Only runs of a suite that appears
    more than once in the plan get one, so that most run names look exactly
    like those from teuthology-suite.
    """
    runs = plan.resolved_runs()
    counts = collections.Counter(run.suite_name for run in runs)
    return {
        run.index: run.ident if counts[run.suite_name] > 1 else None
        for run in runs
    }


def run_conf(args, plan: TestPlan, run: ResolvedRun, timestamp: str,
             suffix: str | None, pinned: dict):
    """Build the teuthology-suite configuration for one run of a plan."""
    conf = process_args(suite_args(args))
    apply_common_args(conf)
    settings = run.settings
    conf.suite = run.suite_name
    conf.timestamp = timestamp
    conf.run_name_suffix = suffix
    if 'subset' in settings:
        conf.subset = tuple(int(i) for i in settings['subset'].split('/'))
    conf.no_nested_subset = settings.get('no_nested_subset', False)
    conf.limit = settings.get('limit', 0)
    conf.filter_in = list(settings.get('filter', []))
    conf.filter_out = list(settings.get('filter_out', []))
    conf.filter_all = list(settings.get('filter_all', []))
    conf.filter_fragments = settings.get('filter_fragments', False)
    conf.distro = settings.get('distro')
    conf.distro_version = settings.get('distro_version')
    if 'seed' in settings:
        conf.seed = settings['seed']
    else:
        conf.seed = random.randint(0, 9999)
        log.info('Using random seed=%s for %s', conf.seed, run.path)
    testplan = dict(name=plan.name, sha256=plan.sha256, run=run.index)
    if run.label:
        testplan['label'] = run.label
    conf.testplan = testplan
    for key, value in pinned.items():
        setattr(conf, key, value)
    return conf


def load_plan(args):
    """
    Fetch the suite repo, then find, load and check the plan in it.

    :returns: (plan, checkout)
    """
    base = process_args(suite_args(args))
    checkout = SuiteCheckout(base)
    plans_dir = testplans_dir(checkout.suite_repo_path, base.suite_relpath)
    # A list, because 'validate' accepts several
    (ref,) = args['<testplan>']
    plan = load(plan_path(ref, plans_dir))
    check_suites(
        plan, suites_dir(checkout.suite_repo_path, base.suite_relpath))
    return plan, checkout


def cmd_run(args):
    plan, checkout = load_plan(args)
    log.info("Scheduling testplan %s from %s (sha256 %s)",
             plan.name, plan.filename, plan.sha256)
    timestamp = datetime.datetime.now().strftime(TIMESTAMP_FMT)
    suffixes = name_suffixes(plan)

    # The first run resolves revisions exactly as teuthology-suite would;
    # the rest reuse them, so that every run tests the same build with the
    # same suite checkout the plan was read from. They were validated by the
    # first run, so they aren't validated again.
    pinned = {}
    if checkout.suite_branch:
        pinned['suite_branch'] = checkout.suite_branch
    runs = []
    for resolved in plan.resolved_runs():
        conf = run_conf(args, plan, resolved, timestamp,
                        suffixes[resolved.index], pinned)
        run = Run(conf)
        if not runs:
            suite_hash = run.config_input['suite_hash']
            if checkout.suite_hash and suite_hash != checkout.suite_hash:
                suite_util.schedule_fail(
                    f"Suite branch {checkout.suite_branch} moved from "
                    f"{checkout.suite_hash} to {suite_hash} while "
                    "scheduling; try again",
                    name=run.name, dry_run=conf.dry_run)
            pinned.update(
                ceph_sha1=run.config_input['ceph_hash'],
                suite_branch=run.config_input['suite_branch'],
                suite_sha1=suite_hash,
                teuthology_branch=run.config_input['teuthology_branch'],
                teuthology_sha1=run.config_input['teuthology_sha1'],
                validate_sha1=False,
            )
        runs.append(run)

    collected = []
    for run in runs:
        run.prepare()
        collected.append(run.collect_suite_jobs())
    total = sum(len(c.jobs_to_schedule) for c in collected)
    log.info("Testplan %s: %d jobs in %d runs", plan.name, total, len(runs))
    runs[0].check_limits(total)
    # Run.schedule_jobs() would fail on missing packages part way through
    # the plan, so check every run before scheduling anything.
    missing = [run.name for run, jobs in zip(runs, collected)
               if jobs.jobs_missing_packages]
    if missing and not config.suite_allow_missing_packages:
        suite_util.schedule_fail(
            "Some jobs need packages that don't exist for hash "
            f"{runs[0].base_config.sha1}, in runs: {', '.join(missing)}",
            name=runs[0].name, dry_run=runs[0].args.dry_run)

    scheduled = []
    for run, jobs in zip(runs, collected):
        count = run.schedule_collected(jobs, check_limits=False)
        if count:
            run.write_result()
        scheduled.append((run.name, count))
    for name, count in scheduled:
        log.info("Scheduled %d jobs in %s", count, name)

    if args['--dry-run'] or not args['--wait']:
        return 0
    exit_code = 0
    for name, count in scheduled:
        if count:
            exit_code = max(exit_code, wait(
                name, config.max_job_time, args['--archive-upload-url']))
    return exit_code


def describe_settings(run: ResolvedRun) -> list[str]:
    lines = []
    for key, value in run.settings.items():
        if isinstance(value, list):
            value = ', '.join(value)
        source = run.sources[key].path
        origin = '  (from defaults)' if source.startswith('defaults') else ''
        lines.append(f"    {key}: {value}{origin}")
    return lines


def cmd_show(args):
    plan, checkout = load_plan(args)
    suites_root = suites_dir(
        checkout.suite_repo_path, args['--suite-relpath'])
    print(f"{plan.name}: {plan.filename}")
    print(f"  sha256: {plan.sha256}")
    if plan.description:
        for line in plan.description.strip().splitlines():
            print(f"  {line}")
    counts = count_all_jobs(plan, suites_root)
    for run in plan.resolved_runs():
        label = f" ({run.label})" if run.label else ''
        print(f"  runs[{run.index}]{label}: {run.suite}, "
              f"{counts[run.index]} jobs")
        for line in describe_settings(run):
            print(line)
    print(f"  total: {sum(counts.values())} jobs")
    print("  (Job counts are estimates: they can't account for missing "
          "packages, jobs excluded by arch at scheduling time, or seeds "
          "chosen at random when scheduling.)")
    return 0


def cmd_list(args):
    base = process_args(suite_args(args))
    checkout = SuiteCheckout(base)
    plans_dir = testplans_dir(checkout.suite_repo_path, base.suite_relpath)
    names = available_plans(plans_dir)
    if not names:
        print(f"No testplans in {plans_dir}")
        return 0
    width = max(len(name) for name in names)
    exit_code = 0
    for name in names:
        try:
            plan = load(os.path.join(plans_dir, name + '.yaml'))
        except ValidationError:
            print(f"{name:<{width}}  (invalid; see 'teuthology-testplan "
                  f"validate')")
            exit_code = 1
            continue
        description = (plan.description or '').strip().splitlines()
        print(f"{name:<{width}}  {description[0] if description else ''}")
    return exit_code


def cmd_validate(args):
    suite_dir = args['--suite-dir']
    relpath = args['--suite-relpath']
    strict = args['--strict']
    count = args['--jobs'] or strict
    if count and not suite_dir:
        raise TestplanError("--jobs and --strict require --suite-dir")
    plans_dir = testplans_dir(suite_dir, relpath) if suite_dir else None
    suites_root = suites_dir(suite_dir, relpath) if suite_dir else None

    exit_code = 0
    for ref in args['<testplan>']:
        try:
            plan = load(plan_path(ref, plans_dir))
            if suites_root:
                check_suites(plan, suites_root)
            counts = count_all_jobs(plan, suites_root) if count else {}
        except (TestplanError, ValidationError) as exc:
            print(exc, file=sys.stderr)
            exit_code = 1
            continue
        runs = plan.resolved_runs()
        summary = f"{plan.filename}: OK, {len(runs)} runs"
        if count:
            empty = [run for run in runs if counts[run.index] == 0]
            summary += f", {sum(counts.values())} jobs"
            for run in empty:
                level = 'error' if strict else 'warning'
                print(FieldError(run.path, run.line,
                                 f"{level}: no jobs").format(plan.filename),
                      file=sys.stderr)
            if empty and strict:
                exit_code = 1
                continue
        print(summary)
    return exit_code
