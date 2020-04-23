import logging

from teuthology.repo_utils import fetch_qa_suite
from teuthology.config import config
from teuthology.exceptions import BranchNotFoundError, GitError

log = logging.getLogger(__name__)


def clone_qa_suite(conf):

    """
    clone qa suit to the local disk to ~/src dir
    :param conf:
    :return: suit_repo_path after cloning for valid suite_repo and suite_branch
    """
    try:
        config.ceph_qa_suite_git_url = conf.suite_repo
        suite_repo_path = fetch_qa_suite(conf.suite_branch)
        return suite_repo_path
    except BranchNotFoundError as exc:
        raise GitError('{}'.format(str(exc)))
