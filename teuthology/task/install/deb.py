import logging
import os
import re

from io import StringIO

from teuthology.orchestra import run
from teuthology.contextutil import safe_while

from teuthology.task.install.util import _get_builder_project, _get_local_dir


log = logging.getLogger(__name__)


RELEASE_KEY_URL = os.environ.get(
    'TEUTH_TASK_INSTALL_RELEASE_KEY_URL',
    'https://git.ceph.com/?p=ceph.git;a=blob_plain;f=keys/autobuild.asc',
)
RELEASE_KEY_PATH = '/etc/apt/trusted.gpg.d/ceph-autobuild.asc'

APT_SOURCES_DIR = '/etc/apt/sources.list.d'
APT_KEYRINGS_DIR = '/etc/apt/keyrings'
# Files we create for custom repos are prefixed so that cleanup can never
# touch a file that was not written by this task.
APT_REPO_PREFIX = 'teuthology-'
APT_REPO_REQUIRED_KEYS = ('name', 'url', 'suite')
APT_REPO_KEYS = APT_REPO_REQUIRED_KEYS + ('components', 'key_url', 'trusted')
_REPO_NAME_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')
_NO_WHITESPACE_RE = re.compile(r'\S+')


def _apt_repo_paths(repo):
    name = APT_REPO_PREFIX + repo['name']
    return (
        '{}/{}.list'.format(APT_SOURCES_DIR, name),
        '{}/{}.asc'.format(APT_KEYRINGS_DIR, name),
    )


def _validate_apt_repos(repos):
    """
    Check a custom ``repos`` list before anything is changed on a remote.

    Each entry must be a dict with ``name`` (used in file names), ``url``,
    ``suite``, ``components`` (a non-empty list, omitted for a flat
    repository whose ``suite`` ends in ``/``, e.g. ``./``) and exactly one of:

    - ``key_url``: an ASCII-armored public key that signs the repository
    - ``trusted: true``: skip signature verification, for repositories that
      are not signed, e.g. one that was just built locally

    :raises ValueError: if the configuration is not usable
    """
    if not isinstance(repos, list):
        raise ValueError("'repos' must be a list of repositories")
    seen = set()
    for repo in repos:
        if not isinstance(repo, dict):
            raise ValueError("Each entry in 'repos' must be a dictionary")
        missing = [k for k in APT_REPO_REQUIRED_KEYS if k not in repo]
        unknown = [k for k in repo if k not in APT_REPO_KEYS]
        if missing or unknown:
            raise ValueError(
                "Invalid apt repo {!r}: missing keys {}, unsupported keys {}; "
                "supported keys are {}".format(
                    repo.get('name'), missing, unknown, list(APT_REPO_KEYS)))
        name = repo['name']
        if not isinstance(name, str) or not _REPO_NAME_RE.fullmatch(name):
            raise ValueError(
                "Invalid apt repo name {!r}: use only letters, digits, "
                "'.', '_' and '-'".format(name))
        if name in seen:
            raise ValueError("Duplicate apt repo name {!r}".format(name))
        seen.add(name)
        components = repo.get('components', [])
        if not isinstance(components, list):
            raise ValueError(
                "'components' of apt repo {!r} must be a list".format(name))
        # A suite ending in '/' is a flat repository, which has no components
        if str(repo['suite']).endswith('/') == bool(components):
            raise ValueError(
                "apt repo {!r} must set 'components' unless 'suite' ends "
                "with '/' (a flat repository), in which case it must not "
                "be set".format(name))
        trusted = repo.get('trusted', False)
        if not isinstance(trusted, bool):
            raise ValueError(
                "'trusted' of apt repo {!r} must be a boolean".format(name))
        if trusted == ('key_url' in repo):
            raise ValueError(
                "apt repo {!r} must set exactly one of 'key_url' or "
                "'trusted: true'".format(name))
        values = [repo['url'], repo['suite']] + components
        if 'key_url' in repo:
            values.append(repo['key_url'])
        if not all(isinstance(v, str) and _NO_WHITESPACE_RE.fullmatch(v)
                   for v in values):
            raise ValueError(
                "Values of apt repo {!r} must be non-empty strings without "
                "whitespace".format(name))


def _apt_addrepos(remote, repos):
    """
    Add custom apt repositories to the remote.

    The key of each repository is stored in its own file and referenced with
    ``signed-by``, so it is trusted for that repository only and signature
    verification stays enabled. Repositories that set ``trusted: true`` are
    added with ``trusted=yes``, which disables verification for them alone.

    :param remote: the teuthology.orchestra.remote.Remote object
    :param repos: list of dicts, see _validate_apt_repos()
    """
    remote.run(args=['sudo', 'install', '-d', '-m', '0755', APT_KEYRINGS_DIR])
    for repo in repos:
        list_path, key_path = _apt_repo_paths(repo)
        log.info("Adding apt repo %s (%s)", repo['name'], repo['url'])
        if repo.get('trusted'):
            log.warning("Signature verification is disabled for apt repo %s",
                        repo['name'])
            option = 'trusted=yes'
        else:
            remote.run(args=[
                'sudo', 'curl', '-sSfL', '-o', key_path, repo['key_url'],
            ])
            option = 'signed-by=' + key_path
        fields = ['deb [%s]' % option, repo['url'], repo['suite']]
        entry = ' '.join(fields + repo.get('components', [])) + '\n'
        remote.sudo_write_file(list_path, entry, mode='0644')


def _ensure_release_key(remote):
    """
    Install the Ceph autobuild signing key if it is not already trusted.

    apt-key is deprecated since Debian 11/Ubuntu 22.04 and gone in Ubuntu
    26.04, so drop the ASCII-armored key straight into trusted.gpg.d
    (supported since apt 1.4) instead of piping it through apt-key.
    """
    remote.sh(
        "set -o pipefail; "
        f"test -s {RELEASE_KEY_PATH} || "
        f"curl -sSfL '{RELEASE_KEY_URL}' | sudo tee {RELEASE_KEY_PATH} > /dev/null"
    )

def _retry_if_eagain_in_output(remote, args):
    # wait at most 5 minutes
    with safe_while(sleep=10, tries=30) as proceed:
        while proceed():
            stderr = StringIO()
            try:
                return remote.run(args=args, stderr=stderr)
            except run.CommandFailedError:
                if "could not get lock" in stderr.getvalue().lower():
                    # Get the PID(s) holding the lock. Set to empty list in case
                    # apt lock is freed between original apt failure and `fuser` call
                    try:
                        pids = remote.sh('sudo fuser /var/lib/dpkg/lock-frontend').split()
                    except run.CommandFailedError:
                        pids = []
                    log.info("The processes holding 'lock-frontend':\n{}".format(pids))

                    # Get detailed info on each PID
                    for pid in pids:
                        try:
                            ps_out = remote.sh(f'ps -p {pid} -o pid,ppid,user,stat,start,etime,cmd')
                            log.info("Process info for PID %s:\n%s", pid, ps_out)

                            cmdline = remote.sh(f'sudo cat /proc/{pid}/cmdline')
                            cmdline = cmdline.replace('\x00', ' ').strip()
                            log.info("Full cmdline for PID %s: %s", pid, cmdline)
                        except run.CommandFailedError:
                            log.info("PID %s exited before we could inspect it", pid)

                    continue
                else:
                    raise

def install_dep_packages(remote, args):
    _retry_if_eagain_in_output(remote, args)

def _update_package_list_and_install(ctx, remote, debs, config):
    """
    Runs ``apt-get update`` first, then runs ``apt-get install``, installing
    the requested packages on the remote system.

    TODO: split this into at least two functions.

    :param ctx: the argparse.Namespace object
    :param remote: the teuthology.orchestra.remote.Remote object
    :param debs: list of packages names to install
    :param config: the config dict
    """

    repos = config.get('repos')
    if repos:
        _validate_apt_repos(repos)
        arch = remote.arch
    else:
        _ensure_release_key(remote)
        builder = _get_builder_project(ctx, remote, config)
        arch = builder.arch
    log.info("Installing packages: {pkglist} on remote deb {arch}".format(
        pkglist=", ".join(debs), arch=arch)
    )
    system_pkglist = config.get('extra_system_packages')
    if system_pkglist:
        if isinstance(system_pkglist, dict):
            system_pkglist = system_pkglist.get('deb')
        log.info("Installing system (non-project) packages: {pkglist} on remote deb {arch}".format(
            pkglist=", ".join(system_pkglist), arch=arch)
        )

    if repos:
        log.info("Using custom apt repos")
        _apt_addrepos(remote, repos)
        pkgs = list(debs)
    else:
        # get baseurl
        log.info('Pulling from %s', builder.base_url)

        version = builder.version
        log.info('Package version is %s', version)

        builder.install_repo()
        pkgs = ['%s=%s' % (d, version) for d in debs]

    # A custom repo that cannot be updated is a configuration error
    remote.run(args=['sudo', 'apt-get', 'update'], check_status=bool(repos))
    install_cmd = [
            'sudo', 'DEBIAN_FRONTEND=noninteractive', 'apt-get', '-y',
            '--force-yes',
            '-o', run.Raw('Dpkg::Options::="--force-confdef"'), '-o', run.Raw(
                'Dpkg::Options::="--force-confold"'),
            'install',
        ]
    install_dep_packages(remote,
        args=install_cmd + pkgs,
    )
    if system_pkglist:
        install_dep_packages(remote,
            args=install_cmd + system_pkglist,
        )
    ldir = _get_local_dir(config, remote)
    if ldir:
        for fyle in os.listdir(ldir):
            fname = "%s/%s" % (ldir, fyle)
            remote.run(args=['sudo', 'dpkg', '-i', fname],)


def _remove(ctx, config, remote, debs):
    """
    Removes Debian packages from remote, rudely

    TODO: be less rude (e.g. using --force-yes)

    :param ctx: the argparse.Namespace object
    :param config: the config dict
    :param remote: the teuthology.orchestra.remote.Remote object
    :param debs: list of packages names to install
    """
    log.info("Removing packages: {pkglist} on Debian system.".format(
        pkglist=", ".join(debs)))
    # first ask nicely
    remote.run(
        args=[
            'for', 'd', 'in',
        ] + debs + [
            run.Raw(';'),
            'do',
            'sudo',
            'DEBIAN_FRONTEND=noninteractive', 'apt-get', '-y', '--force-yes',
            '-o', run.Raw('Dpkg::Options::="--force-confdef"'), '-o', run.Raw(
                'Dpkg::Options::="--force-confold"'), 'purge',
            run.Raw('$d'),
            run.Raw('||'),
            'true',
            run.Raw(';'),
            'done',
        ])
    # mop up anything that is broken
    remote.run(
        args=[
            'dpkg', '-l',
            run.Raw('|'),
            # Any package that is unpacked or half-installed and also requires
            # reinstallation
            'grep', r'^.\(U\|H\)R',
            run.Raw('|'),
            'awk', '{print $2}',
            run.Raw('|'),
            'sudo',
            'xargs', '--no-run-if-empty',
            'dpkg', '-P', '--force-remove-reinstreq',
        ])
    # then let apt clean up
    remote.run(
        args=[
            'sudo',
            'DEBIAN_FRONTEND=noninteractive', 'apt-get', '-y', '--force-yes',
            '-o', run.Raw('Dpkg::Options::="--force-confdef"'), '-o', run.Raw(
                'Dpkg::Options::="--force-confold"'),
            'autoremove',
        ],
    )


def _remove_sources_list(ctx, config, remote):
    repos = config.get('repos')
    if repos:
        paths = [p for repo in repos for p in _apt_repo_paths(repo)]
        remote.run(args=['sudo', 'rm', '-f'] + paths)
    else:
        builder = _get_builder_project(ctx, remote, config)
        builder.remove_repo()
    remote.run(
        args=[
            'sudo', 'apt-get', 'update',
        ],
        check_status=False,
    )


def _upgrade_packages(ctx, config, remote, debs):
    """
    Upgrade project's packages on remote Debian host
    Before doing so, installs the project's GPG key, writes a sources.list
    file, and runs ``apt-get update``.

    :param ctx: the argparse.Namespace object
    :param config: the config dict
    :param remote: the teuthology.orchestra.remote.Remote object
    :param debs: the Debian packages to be installed
    :param branch: the branch of the project to be used
    """
    _ensure_release_key(remote)

    builder = _get_builder_project(ctx, remote, config)
    base_url = builder.base_url
    log.info('Pulling from %s', base_url)

    version = builder.version
    log.info('Package version is %s', version)

    builder.install_repo()

    remote.run(args=['sudo', 'apt-get', 'update'], check_status=False)
    install_dep_packages(remote,
        args=[
            'sudo',
            'DEBIAN_FRONTEND=noninteractive', 'apt-get', '-y', '--force-yes',
            '-o', run.Raw('Dpkg::Options::="--force-confdef"'), '-o', run.Raw(
                'Dpkg::Options::="--force-confold"'),
            'install',
        ] + ['%s=%s' % (d, version) for d in debs],
    )
