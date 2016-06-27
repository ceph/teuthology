import copy
import logging
import os
import pwd
import time
import yaml

from datetime import datetime

from ..config import config, JobConfig
from ..exceptions import (
    BranchNotFoundError, CommitNotFoundError, VersionNotFoundError
)
from ..misc import deep_merge, get_results_url

from . import util
from .build_matrix import combine_path, build_matrix
from .placeholder import substitute_placeholders, dict_templ

log = logging.getLogger(__name__)


class Run(object):
    WAIT_MAX_JOB_TIME = 30 * 60
    WAIT_PAUSE = 5 * 60
    __slots__ = (
        'args', 'name', 'base_config', 'suite_repo_path', 'base_yaml_paths',
        'base_args', 'package_versions', 'kernel_dict', 'config_input',
    )

    def __init__(self, args):
        """
        args must be a config.YamlConfig object
        """
        self.args = args
        self.name = self.make_run_name()
        self.base_config = self.create_initial_config()
        # caches package versions to minimize requests to gbs
        self.package_versions = dict()

        if self.args.suite_dir:
            self.suite_repo_path = self.args.suite_dir
        else:
            self.suite_repo_path = util.fetch_repos(
                self.base_config.suite_branch, test_name=self.name)

        # Interpret any relative paths as being relative to ceph-qa-suite
        # (absolute paths are unchanged by this)
        self.base_yaml_paths = [os.path.join(self.suite_repo_path, b) for b in
                                self.args.base_yaml_paths]

    def make_run_name(self):
        """
        Generate a run name. A run name looks like:
            teuthology-2014-06-23_19:00:37-rados-dumpling-testing-basic-plana
        """
        user = self.args.user or pwd.getpwuid(os.getuid()).pw_name
        # We assume timestamp is a datetime.datetime object
        timestamp = self.args.timestamp or \
            datetime.now().strftime('%Y-%m-%d_%H:%M:%S')

        worker = util.get_worker(self.args.machine_type)
        return '-'.join(
            [
                user, str(timestamp), self.args.suite, self.args.ceph_branch,
                self.args.kernel_branch or '-', self.args.kernel_flavor, worker
            ]
        )

    def create_initial_config(self):
        """
        Put together the config file used as the basis for each job in the run.
        Grabs hashes for the latest ceph, kernel and teuthology versions in the
        branches specified and specifies them so we know exactly what we're
        testing.

        :returns: A JobConfig object
        """
        self.kernel_dict = self.choose_kernel()
        ceph_hash = self.choose_ceph_hash()
        # We don't store ceph_version because we don't use it yet outside of
        # logging.
        self.choose_ceph_version(ceph_hash)
        teuthology_branch = self.choose_teuthology_branch()
        suite_branch = self.choose_suite_branch()
        suite_hash = self.choose_suite_hash(suite_branch)

        self.config_input = dict(
            suite=self.args.suite,
            suite_branch=suite_branch,
            suite_hash=suite_hash,
            ceph_branch=self.args.ceph_branch,
            ceph_hash=ceph_hash,
            teuthology_branch=teuthology_branch,
            machine_type=self.args.machine_type,
            distro=self.args.distro,
            archive_upload=config.archive_upload,
            archive_upload_key=config.archive_upload_key,
        )
        return self.build_base_config()

    def choose_kernel(self):
        # Put together a stanza specifying the kernel hash
        if self.args.kernel_branch == 'distro':
            kernel_hash = 'distro'
        # Skip the stanza if no -k given
        elif self.args.kernel_branch is None:
            kernel_hash = None
        else:
            kernel_hash = util.get_gitbuilder_hash(
                'kernel', self.args.kernel_branch, self.args.kernel_flavor,
                self.args.machine_type, self.args.distro,
            )
            if not kernel_hash:
                util.schedule_fail(
                    message="Kernel branch '{branch}' not found".format(
                        branch=self.args.kernel_branch), name=self.name
                )
        if kernel_hash:
            log.info("kernel sha1: {hash}".format(hash=kernel_hash))
            kernel_dict = dict(kernel=dict(kdb=True, sha1=kernel_hash))
            if kernel_hash is not 'distro':
                kernel_dict['kernel']['flavor'] = self.args.kernel_flavor
        else:
            kernel_dict = dict()
        return kernel_dict

    def choose_ceph_hash(self):
        """
        Get the ceph hash: if --sha1/-S is supplied, use it if it is valid, and
        just keep the ceph_branch around.  Otherwise use the current git branch
        tip.
        """

        if self.args.ceph_sha1:
            ceph_hash = util.git_validate_sha1('ceph', self.args.ceph_sha1)
            if not ceph_hash:
                exc = CommitNotFoundError(self.args.ceph_sha1, 'ceph.git')
                util.schedule_fail(message=str(exc), name=self.name)
            log.info("ceph sha1 explicitly supplied")

        elif self.args.ceph_branch:
            ceph_hash = util.git_ls_remote('ceph', self.args.ceph_branch)
            if not ceph_hash:
                exc = BranchNotFoundError(self.args.ceph_branch, 'ceph.git')
                util.schedule_fail(message=str(exc), name=self.name)

        log.info("ceph sha1: {hash}".format(hash=ceph_hash))
        return ceph_hash

    def choose_ceph_version(self, ceph_hash):
        if config.suite_verify_ceph_hash and not self.args.newest:
            # don't bother if newest; we'll search for an older one
            # Get the ceph package version
            ceph_version = util.package_version_for_hash(
                ceph_hash, self.args.kernel_flavor, self.args.distro,
                self.args.machine_type,
            )
            if not ceph_version:
                util.schedule_fail(
                    "Packages for ceph hash '{ver}' not found".format(
                        ver=ceph_hash), self.name)
            log.info("ceph version: {ver}".format(ver=ceph_version))
            return ceph_version
        else:
            log.info('skipping ceph package verification')

    def choose_teuthology_branch(self):
        teuthology_branch = self.args.teuthology_branch
        if teuthology_branch and teuthology_branch != 'master':
            if not util.git_branch_exists('teuthology', teuthology_branch):
                exc = BranchNotFoundError(teuthology_branch, 'teuthology.git')
                util.schedule_fail(message=str(exc), name=self.name)
        elif not teuthology_branch:
            # Decide what branch of teuthology to use
            if util.git_branch_exists('teuthology', self.args.ceph_branch):
                teuthology_branch = self.args.ceph_branch
            else:
                log.info(
                    "branch {0} not in teuthology.git; will use master for"
                    " teuthology".format(self.args.ceph_branch))
                teuthology_branch = 'master'
        log.info("teuthology branch: %s", teuthology_branch)
        return teuthology_branch

    def choose_suite_branch(self):
        suite_branch = self.args.suite_branch
        ceph_branch = self.args.ceph_branch
        if suite_branch and suite_branch != 'master':
            if not util.git_branch_exists('ceph-qa-suite', suite_branch):
                exc = BranchNotFoundError(suite_branch, 'ceph-qa-suite.git')
                util.schedule_fail(message=str(exc), name=self.name)
        elif not suite_branch:
            # Decide what branch of ceph-qa-suite to use
            if util.git_branch_exists('ceph-qa-suite', ceph_branch):
                suite_branch = ceph_branch
            else:
                log.info(
                    "branch {0} not in ceph-qa-suite.git; will use master for"
                    " ceph-qa-suite".format(ceph_branch))
                suite_branch = 'master'
        return suite_branch

    def choose_suite_hash(self, suite_branch):
        suite_hash = util.git_ls_remote('ceph-qa-suite', suite_branch)
        if not suite_hash:
            exc = BranchNotFoundError(suite_branch, 'ceph-qa-suite.git')
            util.schedule_fail(message=str(exc), name=self.name)
        log.info("ceph-qa-suite branch: %s %s", suite_branch, suite_hash)

    def build_base_config(self):
        conf_dict = substitute_placeholders(dict_templ, self.config_input)
        conf_dict.update(self.kernel_dict)
        job_config = JobConfig.from_dict(conf_dict)
        return job_config

    def build_base_args(self):
        base_args = [
            '--name', self.name,
            '--num', str(self.args.num),
            '--worker', util.get_worker(self.args.machine_type),
        ]
        if self.args.dry_run:
            base_args.append('--dry-run')
        if self.args.priority is not None:
            base_args.extend(['--priority', str(self.args.priority)])
        if self.args.verbose:
            base_args.append('-v')
        if self.args.owner:
            base_args.extend(['--owner', self.args.owner])
        return base_args

    def prepare_and_schedule(self):
        """
        Puts together some "base arguments" with which to execute
        teuthology-schedule for each job, then passes them and other parameters
        to schedule_suite(). Finally, schedules a "last-in-suite" job that
        sends an email to the specified address (if one is configured).
        """
        self.base_args = self.build_base_args()

        # Make sure the yaml paths are actually valid
        for yaml_path in self.base_yaml_paths:
            full_yaml_path = os.path.join(self.suite_repo_path, yaml_path)
            if not os.path.exists(full_yaml_path):
                raise IOError("File not found: " + full_yaml_path)

        num_jobs = self.schedule_suite()

        if self.base_config.email and num_jobs:
            arg = copy.deepcopy(self.base_args)
            arg.append('--last-in-suite')
            arg.extend(['--email', self.base_config.email])
            if self.args.timeout:
                arg.extend(['--timeout', self.args.timeout])
            util.teuthology_schedule(
                args=arg,
                dry_run=self.args.dry_run,
                verbose=self.args.verbose,
                log_prefix="Results email: ",
            )
            results_url = get_results_url(self.base_config.name)
            if results_url:
                log.info("Test results viewable at %s", results_url)

    def collect_jobs(self, arch, configs, newest=False):
        jobs_to_schedule = []
        jobs_missing_packages = []
        for description, fragment_paths in configs:
            base_frag_paths = [
                util.strip_fragment_path(x) for x in fragment_paths
            ]
            limit = self.args.limit
            if limit > 0 and len(jobs_to_schedule) >= limit:
                log.info(
                    'Stopped after {limit} jobs due to --limit={limit}'.format(
                        limit=limit))
                break
            # Break apart the filter parameter (one string) into comma
            # separated components to be used in searches.
            filter_in = self.args.filter_in
            if filter_in:
                filter_list = [x.strip() for x in filter_in.split(',')]
                if not any([x in description for x in filter_list]):
                    all_filt = []
                    for filt_samp in filter_list:
                        all_filt.extend(
                            [x.find(filt_samp) < 0 for x in base_frag_paths]
                        )
                    if all(all_filt):
                        continue
            filter_out = self.args.filter_out
            if filter_out:
                filter_list = [x.strip() for x in filter_out.split(',')]
                if any([x in description for x in filter_list]):
                    continue
                all_filt_val = False
                for filt_samp in filter_list:
                    flist = [filt_samp in x for x in base_frag_paths]
                    if any(flist):
                        all_filt_val = True
                        continue
                if all_filt_val:
                    continue

            raw_yaml = '\n'.join([file(a, 'r').read() for a in fragment_paths])

            parsed_yaml = yaml.load(raw_yaml)
            os_type = parsed_yaml.get('os_type') or self.base_config.os_type
            exclude_arch = parsed_yaml.get('exclude_arch')
            exclude_os_type = parsed_yaml.get('exclude_os_type')

            if exclude_arch and exclude_arch == arch:
                log.info('Skipping due to excluded_arch: %s facets %s',
                         exclude_arch, description)
                continue
            if exclude_os_type and exclude_os_type == os_type:
                log.info('Skipping due to excluded_os_type: %s facets %s',
                         exclude_os_type, description)
                continue

            arg = copy.deepcopy(self.base_args)
            arg.extend([
                '--description', description,
                '--',
            ])
            arg.extend(self.base_yaml_paths)
            arg.extend(fragment_paths)

            job = dict(
                yaml=parsed_yaml,
                desc=description,
                sha1=self.base_config.sha1,
                args=arg
            )

            sha1 = self.base_config.sha1
            if config.suite_verify_ceph_hash:
                full_job_config = dict()
                deep_merge(full_job_config, self.base_config.to_dict())
                deep_merge(full_job_config, parsed_yaml)
                flavor = util.get_install_task_flavor(full_job_config)
                # Get package versions for this sha1, os_type and flavor. If
                # we've already retrieved them in a previous loop, they'll be
                # present in package_versions and gitbuilder will not be asked
                # again for them.
                try:
                    self.package_versions = util.get_package_versions(
                        sha1,
                        os_type,
                        flavor,
                        self.package_versions
                    )
                except VersionNotFoundError:
                    pass
                if not util.has_packages_for_distro(sha1, os_type, flavor,
                                                    self.package_versions):
                    m = "Packages for os_type '{os}', flavor {flavor} and " + \
                        "ceph hash '{ver}' not found"
                    log.error(m.format(os=os_type, flavor=flavor, ver=sha1))
                    jobs_missing_packages.append(job)
                    # optimization: one missing package causes backtrack in newest mode;
                    # no point in continuing the search
                    if newest:
                        return jobs_missing_packages, None

            jobs_to_schedule.append(job)
        return jobs_missing_packages, jobs_to_schedule

    def schedule_jobs(self, jobs_missing_packages, jobs_to_schedule, name):
        for job in jobs_to_schedule:
            log.info(
                'Scheduling %s', job['desc']
            )

            log_prefix = ''
            if job in jobs_missing_packages:
                log_prefix = "Missing Packages: "
                if (
                    not self.args.dry_run and
                    not config.suite_allow_missing_packages
                ):
                    util.schedule_fail(
                        "At least one job needs packages that don't exist for "
                        "hash {sha1}.".format(sha1=self.base_config.sha1),
                        name,
                    )
            util.teuthology_schedule(
                args=job['args'],
                dry_run=self.args.dry_run,
                verbose=self.args.verbose,
                log_prefix=log_prefix,
            )
            throttle = self.args.throttle
            if not self.args.dry_run and throttle:
                log.info("pause between jobs : --throttle " + str(throttle))
                time.sleep(int(throttle))

    def schedule_suite(self):
        """
        Schedule the suite-run. Returns the number of jobs scheduled.
        """
        name = self.name
        arch = util.get_arch(self.base_config.machine_type)
        suite_name = self.base_config.suite
        suite_path = os.path.join(
            self.suite_repo_path, 'suites',
            self.base_config.suite.replace(':', '/'))
        log.debug('Suite %s in %s' % (suite_name, suite_path))
        configs = [
            (combine_path(suite_name, item[0]), item[1]) for item in
            build_matrix(suite_path, subset=self.args.subset)
        ]
        log.info('Suite %s in %s generated %d jobs (not yet filtered)' % (
            suite_name, suite_path, len(configs)))

        # if newest, do this until there are no missing packages
        # if not, do it once
        backtrack = 0
        limit = self.args.newest
        while backtrack < limit:
            jobs_missing_packages, jobs_to_schedule = \
                self.collect_jobs(arch, configs, self.args.newest)
            if jobs_missing_packages and self.args.newest:
                self.base_config.sha1 = \
                    util.find_git_parent('ceph', self.base_config.sha1)
                if self.base_config.sha1 is None:
                    util.schedule_fail(
                        name, message='Backtrack for --newest failed'
                    )
                backtrack += 1
                continue
            if backtrack:
                log.info("--newest supplied, backtracked %d commits to %s" %
                         (backtrack, self.base_config.sha1))
            break
        else:
            if self.args.newest:
                util.schedule_fail(
                    'Exceeded %d backtracks; raise --newest value' % limit,
                    name=name,
                )

        self.schedule_jobs(jobs_missing_packages, jobs_to_schedule, name)

        count = len(jobs_to_schedule)
        missing_count = len(jobs_missing_packages)
        log.info(
            'Suite %s in %s scheduled %d jobs.' %
            (suite_name, suite_path, count)
        )
        log.info('%d/%d jobs were filtered out.',
                 (len(configs) - count),
                 len(configs))
        if missing_count:
            log.warn('Scheduled %d/%d jobs that are missing packages!',
                     missing_count, count)
        return count
