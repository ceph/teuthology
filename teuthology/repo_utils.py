import fcntl
import logging
import os
import re
import shutil
import subprocess
import time

from .config import config
from .contextutil import safe_while, MaxWhileTries
from .exceptions import BootstrapError, BranchNotFoundError, GitError

log = logging.getLogger(__name__)


# Repos must not have been fetched in the last X seconds to get fetched again.
# Similar for teuthology's bootstrap
FRESHNESS_INTERVAL = 60


def touch_file(path):
    out = subprocess.check_output(('touch', path))
    if out:
        log.info(out)


def is_fresh(path):
    """
    Has this file been modified in the last FRESHNESS_INTERVAL seconds?

    Returns False if the file does not exist
    """
    if not os.path.exists(path):
        return False
    elif time.time() - os.stat(path).st_mtime < FRESHNESS_INTERVAL:
        return True
    return False


def build_git_url(project, project_owner='ceph'):
    """
    Return the git URL to clone the project
    """
    if project == 'ceph-qa-suite':
        base = config.get_ceph_qa_suite_git_url()
    elif project == 'ceph':
        base = config.get_ceph_git_url()
    else:
        base = 'https://github.com/{project_owner}/{project}'
    url_templ = re.sub('\.git$', '', base)
    return url_templ.format(project_owner=project_owner, project=project)


def ls_remote(url, ref):
    """
    Return the current sha1 for a given repository and ref

    :returns: The sha1 if found; else None
    """
    cmd = "git ls-remote {} {}".format(url, ref)
    result = subprocess.check_output(
        cmd, shell=True).split()
    sha1 = result[0] if result else None
    log.debug("{} -> {}".format(cmd, sha1))
    return sha1


def enforce_repo_state(repo_url, dest_path, branch, remove_on_error=True):
    """
    Use git to either clone or update a given repo, forcing it to switch to the
    specified branch.

    :param repo_url:  The full URL to the repo (not including the branch)
    :param dest_path: The full path to the destination directory
    :param branch:    The branch.
    :param remove:    Whether or not to remove dest_dir when an error occurs
    :raises:          BranchNotFoundError if the branch is not found;
                      GitError for other errors
    """
    validate_branch(branch)
    sentinel = os.path.join(dest_path, '.fetched')
    try:
        if not os.path.isdir(dest_path):
            clone_repo(repo_url, dest_path, branch)
        elif not is_fresh(sentinel):
            set_remote(dest_path, repo_url)
            fetch(dest_path)
            touch_file(sentinel)
        else:
            log.info("%s was just updated; assuming it is current", dest_path)

        reset_repo(repo_url, dest_path, branch)
        # remove_pyc_files(dest_path)
    except BranchNotFoundError:
        if remove_on_error:
            shutil.rmtree(dest_path, ignore_errors=True)
        raise


def clone_repo(repo_url, dest_path, branch):
    """
    Clone a repo into a path

    :param repo_url:  The full URL to the repo (not including the branch)
    :param dest_path: The full path to the destination directory
    :param branch:    The branch.
    :raises:          BranchNotFoundError if the branch is not found;
                      GitError for other errors
    """
    validate_branch(branch)
    log.info("Cloning %s %s from upstream", repo_url, branch)
    proc = subprocess.Popen(
        ('git', 'clone', '--branch', branch, repo_url, dest_path),
        cwd=os.path.dirname(dest_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)

    not_found_str = "Remote branch %s not found" % branch
    out = proc.stdout.read()
    result = proc.wait()
    # Newer git versions will bail if the branch is not found, but older ones
    # will not. Fortunately they both output similar text.
    if not_found_str in out:
        log.error(out)
        if result == 0:
            # Old git left a repo with the wrong branch. Remove it.
            shutil.rmtree(dest_path, ignore_errors=True)
        raise BranchNotFoundError(branch, repo_url)
    elif result != 0:
        # Unknown error
        raise GitError("git clone failed!")


def set_remote(repo_path, repo_url):
    """
    Call "git remote set-url origin <repo_url>"

    :param repo_url:  The full URL to the repo (not including the branch)
    :param repo_path: The full path to the repository
    :raises:          GitError if the operation fails
    """
    log.debug("Setting repo remote to  %s", repo_url)
    proc = subprocess.Popen(
        ('git', 'remote', 'set-url', 'origin', repo_url),
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)
    if proc.wait() != 0:
        out = proc.stdout.read()
        log.error(out)
        raise GitError("git remote set-url failed!")


def fetch(repo_path):
    """
    Call "git fetch -p origin"

    :param repo_path: The full path to the repository
    :raises:          GitError if the operation fails
    """
    log.info("Fetching from upstream into %s", repo_path)
    proc = subprocess.Popen(
        ('git', 'fetch', '-p', 'origin'),
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)
    if proc.wait() != 0:
        out = proc.stdout.read()
        log.error(out)
        raise GitError("git fetch failed!")


def fetch_branch(repo_path, branch):
    """
    Call "git fetch -p origin <branch>"

    :param repo_path: The full path to the repository on-disk
    :param branch:    The branch.
    :raises:          BranchNotFoundError if the branch is not found;
                      GitError for other errors
    """
    validate_branch(branch)
    log.info("Fetching %s from upstream", branch)
    proc = subprocess.Popen(
        ('git', 'fetch', '-p', 'origin', branch),
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)
    if proc.wait() != 0:
        not_found_str = "fatal: Couldn't find remote ref %s" % branch
        out = proc.stdout.read()
        log.error(out)
        if not_found_str in out:
            raise BranchNotFoundError(branch)
        else:
            raise GitError("git fetch failed!")


def reset_repo(repo_url, dest_path, branch):
    """

    :param repo_url:  The full URL to the repo (not including the branch)
    :param dest_path: The full path to the destination directory
    :param branch:    The branch.
    :raises:          BranchNotFoundError if the branch is not found;
                      GitError for other errors
    """
    validate_branch(branch)
    log.info('Resetting repo at %s to branch %s', dest_path, branch)
    # This try/except block will notice if the requested branch doesn't
    # exist, whether it was cloned or fetched.
    try:
        subprocess.check_output(
            ('git', 'reset', '--hard', 'origin/%s' % branch),
            cwd=dest_path,
        )
    except subprocess.CalledProcessError:
        raise BranchNotFoundError(branch, repo_url)


def remove_pyc_files(dest_path):
    subprocess.check_call(
        ['find', dest_path, '-name', '*.pyc', '-exec', 'rm', '{}', ';']
    )


def validate_branch(branch):
    if ' ' in branch:
        raise ValueError("Illegal branch name: '%s'" % branch)


def fetch_repo(url, branch, bootstrap=None, lock=True):
    """
    Make sure we have a given project's repo checked out and up-to-date with
    the current branch requested

    :param url:        The URL to the repo
    :param bootstrap:  An optional callback function to execute. Gets passed a
                       dest_dir argument: the path to the repo on-disk.
    :param branch:     The branch we want
    :returns:          The destination path
    """
    # 'url/to/project.git' -> 'project'
    name = url.split('/')[-1].split('.git')[0]
    src_base_path = config.src_base_path
    if not os.path.exists(src_base_path):
        os.mkdir(src_base_path)
    dest_path = os.path.join(src_base_path, '%s_%s' % (name, branch))
    # only let one worker create/update the checkout at a time
    lock_path = dest_path.rstrip('/') + '.lock'
    with FileLock(lock_path, noop=not lock):
        with safe_while(sleep=10, tries=60) as proceed:
            try:
                while proceed():
                    try:
                        enforce_repo_state(url, dest_path, branch)
                        if bootstrap:
                            bootstrap(dest_path)
                        break
                    except GitError:
                        log.exception("Git error encountered; retrying")
                    except BootstrapError:
                        log.exception("Bootstrap error encountered; retrying")
            except MaxWhileTries:
                shutil.rmtree(dest_path, ignore_errors=True)
                raise
    return dest_path


def fetch_qa_suite(branch, lock=True, colocated_suite=False):
    """
    Make sure ceph-qa-suite is checked out.

    :param branch:           The branch to fetch
    :param lock:             See fetch_repo()
    :param colocated_suite:  Whether to fetch the ceph repo instead of
                             ceph-qa-suite
    :returns:                The destination path
    """
    if colocated_suite:
        suite_url = config.get_ceph_git_url()
    else:
        suite_url = config.get_ceph_qa_suite_git_url()
    return fetch_repo(suite_url,
                      branch, lock=lock)


def fetch_teuthology(branch, lock=True):
    """
    Make sure we have the correct teuthology branch checked out and up-to-date

    :param branch: The branch we want
    :returns:      The destination path
    """
    url = config.ceph_git_base_url + 'teuthology.git'
    return fetch_repo(url, branch, bootstrap_teuthology, lock)


def bootstrap_teuthology(dest_path):
        sentinel = os.path.join(dest_path, '.bootstrapped')
        if is_fresh(sentinel):
            log.info(
                "Skipping bootstrap as it was already done in the last %ss",
                FRESHNESS_INTERVAL,
            )
            return
        log.info("Bootstrapping %s", dest_path)
        # This magic makes the bootstrap script not attempt to clobber an
        # existing virtualenv. But the branch's bootstrap needs to actually
        # check for the NO_CLOBBER variable.
        env = os.environ.copy()
        env['NO_CLOBBER'] = '1'
        cmd = './bootstrap'
        boot_proc = subprocess.Popen(cmd, shell=True, cwd=dest_path, env=env,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT)
        returncode = boot_proc.wait()
        log.info("Bootstrap exited with status %s", returncode)
        if returncode != 0:
            for line in boot_proc.stdout.readlines():
                log.warn(line.strip())
            venv_path = os.path.join(dest_path, 'virtualenv')
            log.info("Removing %s", venv_path)
            shutil.rmtree(venv_path, ignore_errors=True)
            raise BootstrapError("Bootstrap failed!")
        touch_file(sentinel)


class FileLock(object):
    def __init__(self, filename, noop=False):
        self.filename = filename
        self.file = None
        self.noop = noop

    def __enter__(self):
        if not self.noop:
            assert self.file is None
            self.file = file(self.filename, 'w')
            fcntl.lockf(self.file, fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.noop:
            assert self.file is not None
            fcntl.lockf(self.file, fcntl.LOCK_UN)
            self.file.close()
            self.file = None
