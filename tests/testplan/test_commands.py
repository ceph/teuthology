import itertools
import os

import pytest
import yaml

from mock import DEFAULT, patch

from scripts.testplan import main
from teuthology.config import config
from teuthology.exceptions import ScheduleFailError

SUITE_DIR = os.path.dirname(__file__)
PLANS_DIR = os.path.join(SUITE_DIR, 'qa', 'testplans')
SMOKE = os.path.join(PLANS_DIR, 'smoke.yaml')


class TestValidate:
    def test_file(self, capsys):
        assert main(['validate', SMOKE]) == 0
        assert capsys.readouterr().out == f"{SMOKE}: OK, 3 runs\n"

    def test_name_needs_suite_dir(self, capsys):
        assert main(['validate', 'smoke']) == 1
        assert "pass --suite-dir" in capsys.readouterr().err

    def test_name_with_suite_dir(self, capsys):
        assert main(['validate', '--suite-dir', SUITE_DIR, 'smoke']) == 0
        assert "smoke.yaml: OK, 3 runs" in capsys.readouterr().out

    def test_unknown_name(self, capsys):
        assert main(['validate', '--suite-dir', SUITE_DIR, 'nope']) == 1
        err = capsys.readouterr().err
        assert "no testplan named 'nope'" in err
        assert "broken, empty-filter, smoke" in err

    def test_yml_rejected(self, capsys):
        assert main(['validate', 'plan.yml']) == 1
        assert ".yaml extension" in capsys.readouterr().err

    def test_invalid_plan(self, capsys):
        path = os.path.join(PLANS_DIR, 'broken.yaml')
        assert main(['validate', SMOKE, path]) == 1
        out, err = capsys.readouterr()
        assert out == f"{SMOKE}: OK, 3 runs\n"
        assert err.startswith(f"{path}:4: runs[0].machine_type: ")

    def test_missing_suite(self, capsys, tmp_path):
        path = tmp_path / 'missing.yaml'
        path.write_text("name: x\nruns:\n- suite: alpha\n- suite: gamma/one\n")
        assert main(['validate', '--suite-dir', SUITE_DIR, str(path)]) == 1
        assert capsys.readouterr().err.startswith(
            f"{path}:4: runs[1].suite: suite 'gamma/one' not found in ")

    def test_jobs(self, capsys):
        assert main(['validate', '--suite-dir', SUITE_DIR, '--jobs',
                     'smoke']) == 0
        assert "smoke.yaml: OK, 3 runs, 5 jobs" in capsys.readouterr().out

    def test_jobs_require_suite_dir(self, capsys):
        assert main(['validate', '--jobs', SMOKE]) == 1
        assert "require --suite-dir" in capsys.readouterr().err

    def test_no_jobs_is_warning(self, capsys):
        assert main(['validate', '--suite-dir', SUITE_DIR, '--jobs',
                     'empty-filter']) == 0
        out, err = capsys.readouterr()
        assert "OK, 1 runs, 0 jobs" in out
        assert "empty-filter.yaml:3: runs[0]: warning: no jobs" in err

    def test_no_jobs_is_error_when_strict(self, capsys):
        assert main(['validate', '--suite-dir', SUITE_DIR, '--strict',
                     'empty-filter']) == 1
        out, err = capsys.readouterr()
        assert out == ""
        assert "empty-filter.yaml:3: runs[0]: error: no jobs" in err


def test_list(capsys):
    assert main(['list', '--suite-dir', SUITE_DIR]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "broken        (invalid; see 'teuthology-testplan validate')",
        "empty-filter  ",
        "smoke         Small plan used by the testplan tests.",
    ]


def test_show(capsys):
    assert main(['show', '--suite-dir', SUITE_DIR, 'smoke']) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"smoke: {SMOKE}"
    assert out[2:] == [
        "  Small plan used by the testplan tests.",
        "  Second line of the description.",
        "  runs[0]: alpha, 2 jobs",
        "    limit: 10  (from defaults)",
        "    filter: x",
        "  runs[1] (second): alpha, 2 jobs",
        "    seed: 42",
        "    limit: 10  (from defaults)",
        "    filter_out: x",
        "  runs[2]: beta, 1 jobs",
        "    limit: 10  (from defaults)",
        "    distro: ubuntu",
        "    distro_version: 22.04",
        "  total: 5 jobs",
        "  (Job counts are estimates: they can't account for missing "
        "packages, jobs excluded by arch at scheduling time, or seeds chosen "
        "at random when scheduling.)",
    ]


def test_suite_that_fails_to_build(capsys, tmp_path):
    suite = tmp_path / 'qa' / 'suites' / 'bad'
    suite.mkdir(parents=True)
    (suite / 'x.yaml').write_text("tasks: [\n")
    plan_file = tmp_path / 'plan.yaml'
    plan_file.write_text("name: x\nruns:\n- suite: alpha\n- suite: bad\n")
    (tmp_path / 'qa' / 'suites' / 'alpha').symlink_to(
        os.path.join(SUITE_DIR, 'qa', 'suites', 'alpha'))
    assert main(['validate', '--suite-dir', str(tmp_path), '--jobs',
                 str(plan_file)]) == 1
    assert capsys.readouterr().err.startswith(
        f"{plan_file}:4: runs[1]: could not build suite 'bad': ")


class TestRun:
    @pytest.fixture
    def mocks(self):
        hashes = (f'hash{i}' for i in itertools.count())
        with patch.multiple(
            'teuthology.suite.util',
            fetch_repos=DEFAULT,
            teuthology_schedule=DEFAULT,
            get_arch=lambda x: 'x86_64',
            get_gitbuilder_hash=DEFAULT,
            git_ls_remote=lambda *args: next(hashes),
            git_branch_exists=lambda *args: True,
            package_version_for_hash=DEFAULT,
        ) as m:
            config.suite_verify_ceph_hash = False
            yield m

    def run(self, *extra):
        return main(['run', '--suite-dir', SUITE_DIR, '--machine-type',
                     'smithi', '--owner', 'tester', *extra, 'smoke'])

    @staticmethod
    def scheduled(m_schedule):
        """Return (run name, job yaml or marker) for each schedule call."""
        result = []
        for call in m_schedule.call_args_list:
            args = call.kwargs['args']
            name = args[args.index('--name') + 1]
            if '--first-in-suite' in args:
                result.append((name, 'first'))
            elif '--last-in-suite' in args:
                result.append((name, 'last'))
            else:
                job = yaml.safe_load(call.kwargs['stdin'])
                job['description'] = args[args.index('--description') + 1]
                result.append((name, job))
        return result

    def test_run(self, mocks):
        assert self.run() == 0
        scheduled = self.scheduled(mocks['teuthology_schedule'])
        names = list(dict.fromkeys(name for name, _ in scheduled))
        assert len(names) == 3
        stamp = names[0].split('-')[1:3]
        for name in names:
            assert name.split('-')[1:3] == stamp
        assert names[0].startswith('tester-')
        # alpha appears twice, so both alpha runs get a suffix; beta doesn't
        assert '-alpha.0-' in names[0]
        assert '-alpha.second-' in names[1]
        assert '-beta-' in names[2]

        jobs = [(name, job) for name, job in scheduled
                if isinstance(job, dict)]
        assert len(jobs) == 5
        # Every run tests the same ceph and teuthology revisions
        assert len({(job['sha1'], job['teuthology_sha1'])
                    for _, job in jobs}) == 1
        by_run = {}
        for name, job in jobs:
            by_run.setdefault(name, []).append(job)
        alpha0, alpha1, beta = (by_run[n] for n in names)
        assert all('a/x' in j['description'] for j in alpha0)
        assert not any('a/x' in j['description'] for j in alpha1)
        assert alpha1[0]['seed'] == 42
        assert beta[0]['os_type'] == 'ubuntu'
        assert beta[0]['os_version'] == '22.04'
        assert alpha0[0]['testplan']['name'] == 'smoke'
        assert alpha0[0]['testplan']['run'] == 0
        assert 'label' not in alpha0[0]['testplan']
        assert alpha1[0]['testplan']['label'] == 'second'
        assert len(alpha1[0]['testplan']['sha256']) == 64

        for name in names:
            markers = [job for n, job in scheduled
                       if n == name and isinstance(job, str)]
            assert markers == ['first', 'last']

    def test_job_threshold_applies_to_whole_plan(self, mocks):
        with pytest.raises(ScheduleFailError) as exc:
            self.run('--job-threshold', '4')
        assert "Unable to schedule 5 jobs" in str(exc.value)
        mocks['teuthology_schedule'].assert_not_called()

    def test_missing_packages_schedule_nothing(self, mocks):
        config.suite_verify_ceph_hash = True
        # Only the last run (beta, on ubuntu) is missing packages
        mocks['package_version_for_hash'].side_effect = (
            lambda sha1, flavor, os_type, *args:
            None if os_type == 'ubuntu' else '1.0')
        with pytest.raises(ScheduleFailError) as exc:
            self.run()
        assert "-beta-" in str(exc.value)
        mocks['teuthology_schedule'].assert_not_called()

    def test_newest_not_offered(self, mocks):
        with pytest.raises(SystemExit):
            self.run('--newest', '3')

    def test_fetched_suite_repo(self, mocks):
        mocks['fetch_repos'].return_value = SUITE_DIR
        with patch('teuthology.suite.util.git_ls_remote',
                   lambda url, branch, *args: f'{branch}-sha'):
            assert main(['run', '--machine-type', 'smithi', '-c', 'wip-x',
                         'smoke']) == 0
        commits = {call.kwargs['commit']
                   for call in mocks['fetch_repos'].call_args_list}
        assert commits == {'wip-x-sha'}
        jobs = [job for _, job in
                self.scheduled(mocks['teuthology_schedule'])
                if isinstance(job, dict)]
        assert len(jobs) == 5
        assert {(j['sha1'], j['suite_sha1'], j['suite_branch'])
                for j in jobs} == {('wip-x-sha', 'wip-x-sha', 'wip-x')}

    def test_suite_branch_moved(self, mocks):
        mocks['fetch_repos'].return_value = SUITE_DIR
        suite_hashes = iter(['old', 'new'])

        def ls_remote(url, branch, *args):
            if 'ceph-qa-suite' in url:
                return next(suite_hashes)
            return f'{branch}-sha'

        with patch('teuthology.suite.util.git_ls_remote', ls_remote):
            with pytest.raises(ScheduleFailError) as exc:
                main(['run', '--machine-type', 'smithi', '--suite-repo',
                      'https://example.com/ceph-qa-suite.git', 'smoke'])
        assert "moved from old to new" in str(exc.value)
        mocks['teuthology_schedule'].assert_not_called()

    def test_invalid_plan_schedules_nothing(self, mocks, capsys):
        path = os.path.join(PLANS_DIR, 'broken.yaml')
        assert main(['run', '--suite-dir', SUITE_DIR, path]) == 1
        assert "machine_type" in capsys.readouterr().err
        mocks['teuthology_schedule'].assert_not_called()
