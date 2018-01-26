import contextlib
import logging

from teuthology.nuke import remove_installed_packages, remove_ceph_packages, remove_ceph_data
from teuthology.orchestra import run

log = logging.getLogger(__name__)


@contextlib.contextmanager
def pre_cleanup(ctx, config):
    """
    Ensure the test node doesn't have any ceph files that have escaped
    uninstall from yum or apt-get, Trying to be pristine is a challenge
    but atleast we could ensure whatever we install is uninstalled for
    ceph and its related dependent packages
    """

    if ctx.config.get('run-cm-ansible'):
        log.info("Ceph-cm-ansible task is configured to run, skipping..")
        yield
    else:
        log.info("Remove any previously installed packages")
        remove_installed_packages(ctx)
        remove_ceph_packages(ctx)
        remove_ceph_data(ctx)
        # remove anything/everything in home dir
        ctx.cluster.run(
            args=[
                'sudo', 'rm', '-rf', run.Raw('~/*')
                ],
        )
        yield
