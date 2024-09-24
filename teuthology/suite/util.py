import copy
import functools
import logging
import os
import requests
import smtplib
import socket
from subprocess import Popen, PIPE, DEVNULL
import sys

from email.mime.text import MIMEText

import teuthology.lock.query
import teuthology.lock.util
from teuthology import repo_utils

from teuthology.config import config
from teuthology.exceptions import BranchNotFoundError, ScheduleFailError
from teuthology.misc import deep_merge
from teuthology.repo_utils import fetch_qa_suite, fetch_teuthology
from teuthology.orchestra.opsys import OS, DEFAULT_OS_VERSION
from teuthology.packaging import get_builder_project, VersionNotFoundError
from teuthology.repo_utils import build_git_url
from teuthology.task.install import get_flavor

log = logging.getLogger(__name__)

CONTAINER_DISTRO = 'centos/9'       # the one to check for build_complete
CONTAINER_FLAVOR = 'default'


def fetch_repos(branch, test_name, dry_run, commit=None):
    """
    Fetch the suite repo (and also the teuthology repo) so that we can use it
    to build jobs. Repos are stored in ~/src/.

    The reason the teuthology repo is also fetched is that currently we use
    subprocess to call teuthology-schedule to schedule jobs so we need to make
    sure it is up-to-date. For that reason we always fetch the main branch
    for test scheduling, regardless of what teuthology branch is requested for
    testing.

    :returns: The path to the suite repo on disk
    """
    try:
        # When a user is scheduling a test run from their own copy of
        # teuthology, let's not wreak havoc on it.
        if config.automated_scheduling:
            # We use teuthology's main branch in all cases right now
            if config.teuthology_path is None:
                fetch_teuthology('main')
        suite_repo_path = fetch_qa_suite(branch, commit)
    except BranchNotFoundError as exc:
        schedule_fail(message=str(exc), name=test_name, dry_run=dry_run)
    return suite_repo_path


def schedule_fail(message, name='', dry_run=None):
    """
    If an email address has been specified anywhere, send an alert there. Then
    raise a ScheduleFailError.
    Don't send the mail if --dry-run has been passed.
    """
    email = config.results_email
    if email and not dry_run:
        subject = "Failed to schedule {name}".format(name=name)
        msg = MIMEText(message)
        msg['Subject'] = subject
        msg['From'] = config.results_sending_email
        msg['To'] = email
        try:
            smtp = smtplib.SMTP('localhost')
            smtp.sendmail(msg['From'], [msg['To']], msg.as_string())
            smtp.quit()
        except socket.error:
            log.exception("Failed to connect to mail server!")
    raise ScheduleFailError(message, name)


def get_worker(machine_type):
    """
    Map a given machine_type to a beanstalkd worker. If machine_type mentions
    multiple machine types - e.g. 'plana,mira', then this returns 'multi'.
    Otherwise it returns what was passed.
    """
    if ',' in machine_type:
        return 'multi'
    else:
        return machine_type


def get_gitbuilder_hash(project=None, branch=None, flavor=None,
                        machine_type=None, distro=None,
                        distro_version=None):
    """
    Find the hash representing the head of the project's repository via
    querying a gitbuilder repo.

    Will return None in the case of a 404 or any other HTTP error.
    """
    # Alternate method for github-hosted projects - left here for informational
    # purposes
    # resp = requests.get(
    #     'https://api.github.com/repos/ceph/ceph/git/refs/heads/main')
    # hash = .json()['object']['sha']
    (arch, release, _os) = get_distro_defaults(distro, machine_type)
    if distro is None:
        distro = _os.name
    bp = get_builder_project()(
        project,
        dict(
            branch=branch,
            flavor=flavor,
            os_type=distro,
            os_version=distro_version,
            arch=arch,
        ),
    )
    return bp.sha1


def get_distro_defaults(distro, machine_type):
    """
    Given a distro (e.g. 'ubuntu') and machine type, return:
        (arch, release, pkg_type)
    """
    arch = 'x86_64'
    if distro in (None, 'None', 'rhel'):
        distro = 'centos'

    try:
        os_version = DEFAULT_OS_VERSION[distro]
        os_type = distro
    except IndexError:
        raise ValueError("Invalid distro value passed: %s", distro)
    _os = OS(name=os_type, version=os_version)
    release = get_builder_project()._get_distro(
        _os.name,
        _os.version,
        _os.codename,
    )
    return (
        arch,
        release,
        _os,
    )


def git_ls_remote(project_or_url, branch, project_owner='ceph'):
    """
    Find the latest sha1 for a given project's branch.

    :param project_or_url: Either a project name or a full URL
    :param branch:         The branch to query
    :param project_owner:  The GitHub project owner. Only used when a project
                           name is passed; not when a URL is passed
    :returns: The sha1 if found; else None
    """
    if '://' in project_or_url or project_or_url.startswith('git@'):
        url = project_or_url
    else:
        url = build_git_url(project_or_url, project_owner)
    return repo_utils.ls_remote(url, branch)


def git_validate_sha1(project, sha1, project_owner='ceph'):
    '''
    Use http to validate that project contains sha1
    I can't find a way to do this with git, period, so
    we have specific urls to HEAD for github and git.ceph.com/gitweb
    for now
    '''
    url = build_git_url(project, project_owner)

    if '/github.com/' in url:
        url = '/'.join((url, 'commit', sha1))
    elif '/git.ceph.com/' in url:
        # kinda specific to knowing git.ceph.com is gitweb
        url = ('http://git.ceph.com/?p=%s.git;a=blob_plain;f=.gitignore;hb=%s'
               % (project, sha1))
    else:
        raise RuntimeError(
            'git_validate_sha1: how do I check %s for a sha1?' % url
        )

    resp = requests.head(url)
    if resp.ok:
        return sha1
    return None


def git_branch_exists(project_or_url, branch, project_owner='ceph'):
    """
    Query the git repository to check the existence of a project's branch

    :param project_or_url: Either a project name or a full URL
    :param branch:         The branch to query
    :param project_owner:  The GitHub project owner. Only used when a project
                           name is passed; not when a URL is passed
    """
    return git_ls_remote(project_or_url, branch, project_owner) is not None


def get_branch_info(project, branch, project_owner='ceph'):
    """
    NOTE: This is currently not being used because of GitHub's API rate
    limiting. We use github_branch_exists() instead.

    Use the GitHub API to query a project's branch. Returns:
        {u'object': {u'sha': <a_sha_string>,
                    u'type': <string>,
                    u'url': <url_to_commit>},
        u'ref': u'refs/heads/<branch>',
        u'url': <url_to_branch>}

    We mainly use this to check if a branch exists.
    """
    url_templ = 'https://api.github.com/repos/{project_owner}/{project}/git/refs/heads/{branch}'  # noqa
    url = url_templ.format(project_owner=project_owner, project=project,
                           branch=branch)
    resp = requests.get(url)
    if resp.ok:
        return resp.json()


@functools.lru_cache()
def package_version_for_hash(hash, flavor='default', distro='rhel',
                             distro_version='8.0', machine_type='smithi'):
    """
    Does what it says on the tin. Uses gitbuilder repos.

    :returns: a string.
    """
    (arch, release, _os) = get_distro_defaults(distro, machine_type)
    if distro in (None, 'None'):
        distro = _os.name
    bp = get_builder_project()(
        'ceph',
        dict(
            flavor=flavor,
            os_type=distro,
            os_version=distro_version,
            arch=arch,
            sha1=hash,
        ),
    )

    if (bp.distro == CONTAINER_DISTRO and bp.flavor == CONTAINER_FLAVOR and 
            not bp.build_complete):
        log.info("Container build incomplete")
        return None

    try:
        return bp.version
    except VersionNotFoundError:
        return None


def get_arch(machine_type):
    """
    Based on a given machine_type, return its architecture by querying the lock
    server.

    :returns: A string or None
    """
    result = teuthology.lock.query.list_locks(machine_type=machine_type, count=1, tries=1)
    if not result:
        log.warning("No machines found with machine_type %s!", machine_type)
    else:
        return result[0]['arch']


def strip_fragment_path(original_path):
    """
    Given a path, remove the text before '/suites/'.  Part of the fix for
    http://tracker.ceph.com/issues/15470
    """
    scan_after = '/suites/'
    scan_start = original_path.find(scan_after)
    if scan_start > 0:
        return original_path[scan_start + len(scan_after):]
    return original_path


def get_install_task_flavor(job_config):
    """
    Pokes through the install task's configuration (including its overrides) to
    figure out which flavor it will want to install.

    Only looks at the first instance of the install task in job_config.
    """
    project, = job_config.get('project', 'ceph'),
    tasks = job_config.get('tasks', dict())
    overrides = job_config.get('overrides', dict())
    install_overrides = overrides.get('install', dict())
    project_overrides = install_overrides.get(project, dict())
    first_install_config = dict()
    for task in tasks:
        if list(task.keys())[0] == 'install':
            first_install_config = list(task.values())[0] or dict()
            break
    first_install_config = copy.deepcopy(first_install_config)
    deep_merge(first_install_config, install_overrides)
    deep_merge(first_install_config, project_overrides)
    return get_flavor(first_install_config)


def teuthology_schedule(args, verbose, dry_run, log_prefix='', stdin=None):
    """
    Run teuthology-schedule to schedule individual jobs.

    If --dry-run has been passed but --verbose has been passed just once, don't
    actually run the command - only print what would be executed.

    If --dry-run has been passed and --verbose has been passed multiple times,
    do both.
    """
    exec_path = os.path.join(
        os.path.dirname(sys.argv[0]),
        'teuthology-schedule')
    args.insert(0, exec_path)
    if dry_run:
        # Quote any individual args so that individual commands can be copied
        # and pasted in order to execute them individually.
        printable_args = []
        for item in args:
            if ' ' in item:
                printable_args.append("'%s'" % item)
            else:
                printable_args.append(item)
        log.debug('{0} command: {1}'.format(
            log_prefix,
            ' '.join(printable_args),
        ))
    if not dry_run or (dry_run and verbose > 1):
        astdin = DEVNULL if stdin is None else PIPE
        p = Popen(args, stdin=astdin)
        if stdin is not None:
            p.communicate(input=stdin.encode('utf-8'))
        else:
            p.communicate()

def find_git_parents(project: str, sha1: str, count=1):

    base_url = config.githelper_base_url
    if not base_url:
        log.warning('githelper_base_url not set, --newest disabled')
        return []

    def refresh():
        url = f"{base_url}/{project}.git/refresh"
        log.info(f"Forcing refresh of git mirror: {url}")
        resp = requests.get(url)
        if not resp.ok:
            log.error('git refresh failed for %s: %s',
                      project, resp.content.decode())

    def get_sha1s(project, committish, count):
        url = f"{base_url}/{project}.git/history?committish={committish}&count={count}"
        log.info(f"Looking for parent commits: {url}")
        resp = requests.get(url)
        resp.raise_for_status()
        sha1s = resp.json()['sha1s']
        if len(sha1s) != count:
            resp_json = resp.json()
            err_msg = resp_json.get("error") or resp_json.get("err")
            log.debug(f"Got {resp.status_code} response: {resp_json}")
            log.error(f"Can't find {count} parents of {sha1} in {project}: {err_msg}")
        return sha1s

    # index 0 will be the commit whose parents we want to find.
    # So we will query for count+1, and strip index 0 from the result.
    sha1s = get_sha1s(project, sha1, count + 1)
    if not sha1s:
        log.error("Will try to refresh git mirror and try again")
        refresh()
        sha1s = get_sha1s(project, sha1, count + 1)
    if sha1s:
        return sha1s[1:]
    return []
