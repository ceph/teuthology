import logging
import ast
import re
import requests

from cStringIO import StringIO

from .config import config
from .contextutil import safe_while
from .exceptions import VersionNotFoundError
from .orchestra.opsys import OS, DEFAULT_OS_VERSION

log = logging.getLogger(__name__)

'''
Map 'generic' package name to 'flavor-specific' package name.
If entry is None, either the package isn't known here, or
it's known but should not be installed on remotes of this flavor
'''

_PACKAGE_MAP = {
    'sqlite': {'deb': 'sqlite3', 'rpm': None}
}

'''
Map 'generic' service name to 'flavor-specific' service name.
'''
_SERVICE_MAP = {
    'httpd': {'deb': 'apache2', 'rpm': 'httpd'}
}


def get_package_name(pkg, rem):
    """
    Find the remote-specific name of the generic 'pkg'
    """
    flavor = rem.os.package_type

    try:
        return _PACKAGE_MAP[pkg][flavor]
    except KeyError:
        return None


def get_service_name(service, rem):
    """
    Find the remote-specific name of the generic 'service'
    """
    flavor = rem.os.package_type
    try:
        return _SERVICE_MAP[service][flavor]
    except KeyError:
        return None


def install_package(package, remote):
    """
    Install 'package' on 'remote'
    Assumes repo has already been set up (perhaps with install_repo)
    """
    log.info('Installing package %s on %s', package, remote)
    flavor = remote.os.package_type
    if flavor == 'deb':
        pkgcmd = ['DEBIAN_FRONTEND=noninteractive',
                  'sudo',
                  '-E',
                  'apt-get',
                  '-y',
                  'install',
                  '{package}'.format(package=package)]
    elif flavor == 'rpm':
        if remote.os.name != 'opensuse':
            pkg_mng_cmd = 'yum'
            pkg_mng_opts = '-y'
            pkg_mng_subcommand_opts = ''
        else:
            pkg_mng_cmd = 'zypper'
            pkg_mng_opts = '-n'
            pkg_mng_subcommand_opts = '--capability'

        pkgcmd = ['sudo',
                  pkg_mng_cmd,
                  pkg_mng_opts,
                  'install',
                  pkg_mng_subcommand_opts,
                  '{package}'.format(package=package)]
    else:
        log.error('install_package: bad flavor ' + flavor + '\n')
        return False
    return remote.run(args=pkgcmd)


def remove_package(package, remote):
    """
    Remove package from remote
    """
    flavor = remote.os.package_type
    if flavor == 'deb':
        pkgcmd = ['DEBIAN_FRONTEND=noninteractive',
                  'sudo',
                  '-E',
                  'apt-get',
                  '-y',
                  'purge',
                  '{package}'.format(package=package)]
    elif flavor == 'rpm':
        if remote.os.name != 'opensuse':
            pkg_mng_cmd = 'yum'
            pkg_mng_opts = '-y'
            pkg_mng_action = 'erase'
        else:
            pkg_mng_cmd = 'zypper'
            pkg_mng_opts = '-n'
            pkg_mng_action = 'remove'

        pkgcmd = ['sudo',
                  pkg_mng_cmd,
                  pkg_mng_opts,
                  pkg_mng_action,
                  '{package}'.format(package=package)]
    else:
        log.error('remove_package: bad flavor ' + flavor + '\n')
        return False
    return remote.run(args=pkgcmd)

def clean_repo_caches(clean_args, remote):
    """
    Clean repository cache
    """
    flavor = remote.os.package_type
    if flavor == 'deb':
        pkgcmd = ['DEBIAN_FRONTEND=noninteractive',
                  'sudo',
                  'apt-get',
                  '-y',
                  'clean']
    elif flavor == 'rpm':
        if remote.os.name != 'opensuse':
            pkg_mng_cmd = 'yum'
            pkg_mng_opts = '-y'
        else:
            pkg_mng_cmd = 'zypper'
            pkg_mng_opts = '-n'

        pkgcmd = ['sudo',
                  pkg_mng_cmd,
                  pkg_mng_opts,
                  'clean',
                  clean_args]
    else:
        log.error('clean_repo_caches: bad flavor ' + flavor + '\n')
        return False
    return remote.run(args=pkgcmd)

def get_koji_task_result(task_id, remote, ctx):
    """
    Queries kojihub and retrieves information about
    the given task_id. The package, koji, must be installed
    on the remote for this command to work.

    We need a remote here because koji can only be installed
    on rpm based machines and teuthology runs on Ubuntu.

    The results of the given task are returned. For example:

    {
      'brootid': 3303567,
      'srpms': [],
      'rpms': [
          'tasks/6745/9666745/kernel-4.1.0-0.rc2.git2.1.fc23.x86_64.rpm',
          'tasks/6745/9666745/kernel-modules-4.1.0-0.rc2.git2.1.fc23.x86_64.rpm',
       ],
      'logs': []
    }

    :param task_id:   The koji task_id we want to retrieve results for.
    :param remote:    The remote to run the koji command on.
    :param ctx:       The ctx from the current run, used to provide a
                      failure_reason and status if the koji command fails.
    :returns:         A python dict containing info about the task results.
    """
    py_cmd = ('import koji; '
              'hub = koji.ClientSession("{kojihub_url}"); '
              'print hub.getTaskResult({task_id})')
    py_cmd = py_cmd.format(
        task_id=task_id,
        kojihub_url=config.kojihub_url
    )
    log.info("Querying kojihub for the result of task {0}".format(task_id))
    task_result = _run_python_command(py_cmd, remote, ctx)
    return task_result


def get_koji_task_rpm_info(package, task_rpms):
    """
    Extracts information about a given package from the provided
    rpm results of a koji task.

    For example, if trying to retrieve the package 'kernel' from
    the results of a task, the output would look like this:

    {
      'base_url': 'https://kojipkgs.fedoraproject.org/work/tasks/6745/9666745/',
      'rpm_name': 'kernel-4.1.0-0.rc2.git2.1.fc23.x86_64.rpm',
      'package_name': 'kernel',
      'version': '4.1.0-0.rc2.git2.1.fc23.x86_64',
    }

    :param task_rpms:    A list of rpms from a tasks reusults.
    :param package:      The name of the package to retrieve.
    :returns:            A python dict containing info about the package.
    """
    result = dict()
    result['package_name'] = package
    found_pkg = _find_koji_task_result(package, task_rpms)
    if not found_pkg:
        raise RuntimeError("The package {pkg} was not found in: {rpms}".format(
            pkg=package,
            rpms=task_rpms,
        ))

    path, rpm_name = found_pkg.rsplit("/", 1)
    result['rpm_name'] = rpm_name
    result['base_url'] = "{koji_task_url}/{path}/".format(
        koji_task_url=config.koji_task_url,
        path=path,
    )
    # removes the package name from the beginning of rpm_name
    version = rpm_name.split("{0}-".format(package), 1)[1]
    # removes .rpm from the rpm_name
    version = version.split(".rpm")[0]
    result['version'] = version
    return result


def _find_koji_task_result(package, rpm_list):
    """
    Looks in the list of rpms from koji task results to see if
    the package we are looking for is present.

    Returns the full list item, including the path, if found.

    If not found, returns None.
    """
    for rpm in rpm_list:
        if package == _get_koji_task_result_package_name(rpm):
            return rpm
    return None


def _get_koji_task_result_package_name(path):
    """
    Strips the package name from a koji rpm result.

    This makes the assumption that rpm names are in the following
    format: <package_name>-<version>.<release>.<arch>.rpm

    For example, given a koji rpm result might look like:

    tasks/6745/9666745/kernel-4.1.0-0.rc2.git2.1.fc23.x86_64.rpm

    This method would return "kernel".
    """
    filename = path.split('/')[-1]
    trimmed = []
    for part in filename.split('-'):
        # assumes that when the next part is not a digit
        # we're past the name and at the version
        if part[0].isdigit():
            return '-'.join(trimmed)
        trimmed.append(part)

    return '-'.join(trimmed)


def get_koji_build_info(build_id, remote, ctx):
    """
    Queries kojihub and retrieves information about
    the given build_id. The package, koji, must be installed
    on the remote for this command to work.

    We need a remote here because koji can only be installed
    on rpm based machines and teuthology runs on Ubuntu.

    Here is an example of the build info returned:

    {'owner_name': 'kdreyer', 'package_name': 'ceph',
     'task_id': 8534149, 'completion_ts': 1421278726.1171,
     'creation_event_id': 10486804, 'creation_time': '2015-01-14 18:15:17.003134',
     'epoch': None, 'nvr': 'ceph-0.80.5-4.el7ost', 'name': 'ceph',
     'completion_time': '2015-01-14 18:38:46.1171', 'state': 1, 'version': '0.80.5',
     'volume_name': 'DEFAULT', 'release': '4.el7ost', 'creation_ts': 1421277317.00313,
     'package_id': 34590, 'id': 412677, 'volume_id': 0, 'owner_id': 2826
    }

    :param build_id:  The koji build_id we want to retrieve info on.
    :param remote:    The remote to run the koji command on.
    :param ctx:       The ctx from the current run, used to provide a
                      failure_reason and status if the koji command fails.
    :returns:         A python dict containing info about the build.
    """
    py_cmd = ('import koji; '
              'hub = koji.ClientSession("{kojihub_url}"); '
              'print hub.getBuild({build_id})')
    py_cmd = py_cmd.format(
        build_id=build_id,
        kojihub_url=config.kojihub_url
    )
    log.info('Querying kojihub for info on build {0}'.format(build_id))
    build_info = _run_python_command(py_cmd, remote, ctx)
    return build_info


def _run_python_command(py_cmd, remote, ctx):
    """
    Runs the given python code on the remote
    and returns the stdout from the code as
    a python object.
    """
    proc = remote.run(
        args=[
            'python', '-c', py_cmd
        ],
        stdout=StringIO(), stderr=StringIO(), check_status=False
    )
    if proc.exitstatus == 0:
        # returns the __repr__ of a python dict
        stdout = proc.stdout.getvalue().strip()
        # take the __repr__ and makes it a python dict again
        result = ast.literal_eval(stdout)
    else:
        msg = "Error running the following on {0}: {1}".format(remote, py_cmd)
        log.error(msg)
        log.error("stdout: {0}".format(proc.stdout.getvalue().strip()))
        log.error("stderr: {0}".format(proc.stderr.getvalue().strip()))
        ctx.summary["failure_reason"] = msg
        ctx.summary["status"] = "dead"
        raise RuntimeError(msg)

    return result


def get_kojiroot_base_url(build_info, arch="x86_64"):
    """
    Builds the base download url for kojiroot given the current
    build information.

    :param build_info:  A dict of koji build information, possibly
                        retrieved from get_koji_build_info.
    :param arch:        The arch you want to download rpms for.
    :returns:           The base_url to use when downloading rpms
                        from brew.
    """
    base_url = "{kojiroot}/{package_name}/{ver}/{rel}/{arch}/".format(
        kojiroot=config.kojiroot_url,
        package_name=build_info["package_name"],
        ver=build_info["version"],
        rel=build_info["release"],
        arch=arch,
    )
    return base_url


def get_koji_package_name(package, build_info, arch="x86_64"):
    """
    Builds the package name for a brew rpm.

    :param package:     The name of the package
    :param build_info:  A dict of koji build information, possibly
                        retrieved from get_brew_build_info.
    :param arch:        The arch you want to download rpms for.
    :returns:           A string representing the file name for the
                        requested package in koji.
    """
    pkg_name = "{name}-{ver}-{rel}.{arch}.rpm".format(
        name=package,
        ver=build_info["version"],
        rel=build_info["release"],
        arch=arch,
    )

    return pkg_name


def get_package_version(remote, package):
    installed_ver = None
    if remote.os.package_type == "deb":
        proc = remote.run(
            args=[
                'dpkg-query', '-W', '-f', '${Version}', package
            ],
            stdout=StringIO(),
        )
    else:
        proc = remote.run(
            args=[
                'rpm', '-q', package, '--qf', '%{VERSION}'
            ],
            stdout=StringIO(),
        )
    if proc.exitstatus == 0:
        installed_ver = proc.stdout.getvalue().strip()
        # Does this look like a version string?
        # this assumes a version string starts with non-alpha characters
        if installed_ver and re.match('^[^a-zA-Z]', installed_ver):
            log.info("The installed version of {pkg} is {ver}".format(
                pkg=package,
                ver=installed_ver,
            ))
        else:
            installed_ver = None
    else:
        # should this throw an exception and stop the job?
        log.warning(
            "Unable to determine if {pkg} is installed: {stdout}".format(
                pkg=package,
                stdout=proc.stdout.getvalue().strip(),
            )
        )

    return installed_ver


def _get_config_value_for_remote(ctx, remote, config, key):
    """
    Look through config, and attempt to determine the "best" value to use
    for a given key. For example, given::

        config = {
            'all':
                {'branch': 'master'},
            'branch': 'next'
        }
        _get_config_value_for_remote(ctx, remote, config, 'branch')

    would return 'master'.

    :param ctx: the argparse.Namespace object
    :param remote: the teuthology.orchestra.remote.Remote object
    :param config: the config dict
    :param key: the name of the value to retrieve
    """
    roles = ctx.cluster.remotes[remote]
    if 'all' in config:
        return config['all'].get(key)
    elif roles:
        for role in roles:
            if role in config and key in config[role]:
                return config[role].get(key)
    return config.get(key)


def _get_response(url, wait=False, sleep=15, tries=10):
    with safe_while(sleep=sleep, tries=tries, _raise=False) as proceed:
        while proceed():
            resp = requests.get(url)
            if resp.ok:
                log.info('Package found...')
                break

            if not wait:
                log.info(
                    'Package is not found at: %s (got HTTP code %s)...',
                    url,
                    resp.status_code,
                )
                break

            log.info(
                'Package not there yet (got HTTP code %s), waiting...',
                resp.status_code,
            )

    return resp


class GitbuilderProject(object):
    """
    Represents a project that is built by gitbuilder.
    """

    def __init__(self, project, job_config, ctx=None, remote=None):
        self.project = project
        self.job_config = job_config
        #TODO: we could get around the need for ctx by using a list
        # of roles instead, ctx is only used in _get_config_value_for_remote.
        self.ctx = ctx
        self.remote = remote

        if remote and ctx:
            self._init_from_remote()
        else:
            self._init_from_config()

        self.dist_release = self._get_dist_release()

    def _init_from_remote(self):
        """
        Initializes the class from a teuthology.orchestra.remote.Remote object
        """
        self.arch = self.remote.arch
        self.os_type = self.remote.os.name
        self.os_version = self.remote.os.version
        self.pkg_type = self.remote.system_type
        self.distro = self._get_distro(
            distro=self.remote.os.name,
            version=self.remote.os.version,
            codename=self.remote.os.codename,
        )
        # when we're initializing with a remote we most likely have
        # a task config, not the entire teuthology job config
        self.flavor = self.job_config.get("flavor", "basic")

    def _init_from_config(self):
        """
        Initializes the class from a teuthology job config
        """
        self.arch = self.job_config.get('arch', 'x86_64')
        self.os_type = self.job_config.get("os_type")
        self.flavor = self.job_config.get("flavor")
        self.codename = self.job_config.get("codename")
        self.os_version = self._get_version()
        # if os_version is given, prefer version/codename derived from it
        if self.os_version:
            self.os_version, self.codename = \
                OS.version_codename(self.os_type, self.os_version)
        self.branch = self.job_config.get("branch")
        self.tag = self.job_config.get("tag")
        self.ref = self.job_config.get("ref")
        self.distro = self._get_distro(
            distro=self.os_type,
            version=self.os_version,
            codename=self.codename,
        )
        self.pkg_type = "deb" if self.os_type.lower() in (
            "ubuntu",
            "debian",
        ) else "rpm"

        if not getattr(self, 'flavor'):
            # avoiding circular imports
            from teuthology.suite.util import get_install_task_flavor
            # when we're initializing from a full teuthology config, not just a
            # task config we need to make sure we're looking at the flavor for
            # the install task
            self.flavor = get_install_task_flavor(self.job_config)

    @property
    def sha1(self):
        """
        Performs a call to gitbuilder to retrieve the sha1 if not provided in
        the job_config. The returned value is cached so that this call only
        happens once.

        :returns: The sha1 of the project as a string.
        """
        if not hasattr(self, "_sha1"):
            self._sha1 = self.job_config.get('sha1')
            if not self._sha1:
                self._sha1 = self._get_package_sha1()
        return self._sha1

    @property
    def version(self):
        """
        Performs a call to gitubilder to retrieve the version number for the
        project. The returned value is cached so that this call only happens
        once.

        :returns: The version number of the project as a string.
        """
        if not hasattr(self, '_version'):
            self._version = self._get_package_version()
        return self._version

    @property
    def base_url(self):
        """
        The base url that points at this project on gitbuilder.

        For example::

            http://gitbuilder.ceph.com/ceph-deb-raring-x86_64-basic/ref/master

        :returns: A string of the base url for this project
        """
        return self._get_base_url()

    @property
    def uri_reference(self):
        """
        The URI reference that identifies what build of the project
        we'd like to use.

        For example, the following could be returned::

            ref/<branch>
            sha1/<sha1>
            ref/<tag>

        :returns: The uri_reference as a string.
        """
        return self._get_uri_reference()

    def _get_dist_release(self):
        version = self._parse_version(self.os_version)
        if self.os_type in ('centos', 'rhel'):
            return "el{0}".format(version)
        elif self.os_type == "fedora":
            return "fc{0}".format(version)
        else:
            # debian and ubuntu just use the distro name
            return self.os_type

    @staticmethod
    def _parse_version(version):
        """
        Parses a distro version string and returns a modified string
        that matches the format needed for the gitbuilder url.

        Minor version numbers are ignored.
        """
        return version.split(".")[0]

    @classmethod
    def _get_distro(cls, distro=None, version=None, codename=None):
        """
        Given a distro and a version, returned the combined string
        to use in a gitbuilder url.

        :param distro:   The distro as a string
        :param version:  The version as a string
        :param codename: The codename for the distro.
                         Used for deb based distros.
        """
        if distro in ('centos', 'rhel'):
            distro = "centos"
        elif distro == "fedora":
            distro = "fedora"
        elif distro == "opensuse":
            distro = "opensuse"
        else:
            # deb based systems use codename instead of a distro/version combo
            if not codename:
                # lookup codename based on distro string
                codename = OS._version_to_codename(distro, version)
                if not codename:
                    msg = "No codename found for: {distro} {version}".format(
                        distro=distro,
                        version=version,
                    )
                    log.exception(msg)
                    raise RuntimeError()
            return codename

        return "{distro}{version}".format(
            distro=distro,
            version=cls._parse_version(version),
        )

    def _get_version(self):
        """
        Attempts to find the distro version from the job_config.

        If not found, it will return the default version for
        the distro found in job_config.

        :returns: A string distro version
        """
        version = self.job_config.get("os_version")
        if not version:
            version = DEFAULT_OS_VERSION.get(self.os_type)

        return version

    def _get_uri_reference(self):
        """
        Returns the URI reference that identifies what build of the project
        we'd like to use.

        If a remote is given, it will attempt to read the config for the given
        remote to find either a tag, branch or sha1 defined. If there is no
        remote, the sha1 from the config will be used.

        If a tag, branch or sha1 can't be found it will default to use the
        build from the master branch.

        :returns: A string URI. Ex: ref/master
        """
        tag = branch = sha1 = None
        if self.remote:
            tag = _get_config_value_for_remote(self.ctx, self.remote,
                                               self.job_config, 'tag')
            branch = _get_config_value_for_remote(self.ctx, self.remote,
                                                  self.job_config, 'branch')
            sha1 = _get_config_value_for_remote(self.ctx, self.remote,
                                                self.job_config, 'sha1')
            ref = None
        else:
            ref = self.ref
            tag = self.tag
            branch = self.branch
            sha1 = self.sha1

        def warn(attrname):
            names = ('ref', 'tag', 'branch', 'sha1')
            vars = (ref, tag, branch, sha1)
            # filter(None,) filters for truth
            if len(filter(None, vars)) > 1:
                log.warning(
                    'More than one of ref, tag, branch, or sha1 supplied; using %s',
                     attrname
                )
                for n, v in zip(names, vars):
                    log.info('%s: %s' % (n, v))

        if ref:
            uri = 'ref'/ + ref
            warn('ref')
        elif tag:
            uri = 'ref/' + tag
            warn('tag')
        elif branch:
            uri = 'ref/' + branch
            warn('branch')
        elif sha1:
            uri = 'sha1/' + sha1
            warn('sha1')
        else:
            log.warning("defaulting to master branch")
            uri = getattr(self, 'ref', 'ref/master')
        return uri

    def _get_base_url(self):
        """
        Figures out which package repo base URL to use.
        """
        template = config.baseurl_template
        # get distro name and arch
        base_url = template.format(
            host=config.gitbuilder_host,
            proj=self.project,
            pkg_type=self.pkg_type,
            arch=self.arch,
            dist=self.distro,
            flavor=self.flavor,
            uri=self.uri_reference,
        )
        return base_url

    def _get_package_version(self):
        """
        Look for, and parse, a file called 'version' in base_url.
        """
        url = "{0}/version".format(self.base_url)
        log.info("Looking for package version: {0}".format(url))
        # will loop and retry until a 200 is returned or the retry
        # limits are reached
        resp = _get_response(url, wait=self.job_config.get("wait_for_package", False))

        if not resp.ok:
            raise VersionNotFoundError(url)
        version = resp.text.strip()
        if self.pkg_type == "rpm" and self.project == "ceph":
            # TODO: move this parsing into a different function for
            # easier testing
            # FIXME: 'version' as retreived from the repo is actually the
            # RPM version PLUS *part* of the release. Example:
            # Right now, ceph master is given the following version in the
            # repo file: v0.67-rc3.164.gd5aa3a9 - whereas in reality the RPM
            # version is 0.61.7 and the release is 37.g1243c97.el6 (centos6).
            # Point being, I have to mangle a little here.
            if version[0] == 'v':
                version = version[1:]
            if '-' in version:
                version = version.split('-')[0]
        log.info("Found version: {0}".format(version))
        return version

    def _get_package_sha1(self):
        """
        Look for, and parse, a file called 'sha1' in base_url.
        """
        url = "{0}/sha1".format(self.base_url)
        log.info("Looking for package sha1: {0}".format(url))
        resp = requests.get(url)
        sha1 = None
        if not resp.ok:
            # TODO: maybe we should have this retry a few times?
            log.error(
                'Package sha1 was not there (got HTTP code %s)...',
                resp.status_code,
            )
        else:
            sha1 = resp.text.strip()
            log.info("Found sha1: {0}".format(sha1))

        return sha1
