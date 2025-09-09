"""
Miscellaneous teuthology functions.
Used by other modules, but mostly called from tasks.
"""
import argparse
import os
import logging
import configobj
import getpass
import shutil
import socket
import subprocess
import tarfile
import time
import yaml
import json
import re
from sys import stdin
import pprint
import datetime

from tarfile import ReadError

from typing import Optional, TypeVar

from teuthology.util.compat import urljoin, urlopen, HTTPError

from netaddr.strategy.ipv4 import valid_str as _is_ipv4
from netaddr.strategy.ipv6 import valid_str as _is_ipv6
from teuthology import safepath
from teuthology.exceptions import (CommandCrashedError, CommandFailedError,
                                   ConnectionLostError)
from teuthology.orchestra import run
from teuthology.config import config
from teuthology.contextutil import safe_while
from teuthology.orchestra.opsys import DEFAULT_OS_VERSION


log = logging.getLogger(__name__)

stamp = datetime.datetime.now().strftime("%y%m%d%H%M")

is_arm = lambda x: x.startswith('tala') or x.startswith(
    'ubuntu@tala') or x.startswith('saya') or x.startswith('ubuntu@saya')

hostname_expr_templ = '(?P<user>.*@)?(?P<shortname>.*){lab_domain}'

def host_shortname(hostname):
    if _is_ipv4(hostname) or _is_ipv6(hostname):
        return hostname
    else:
        return hostname.split('.', 1)[0]

def canonicalize_hostname(hostname, user: Optional[str] ='ubuntu'):
    hostname_expr = hostname_expr_templ.format(
        lab_domain=config.lab_domain.replace('.', r'\.'))
    match = re.match(hostname_expr, hostname)
    if _is_ipv4(hostname) or _is_ipv6(hostname):
        return "%s@%s" % (user, hostname)
    if match:
        match_d = match.groupdict()
        shortname = match_d['shortname']
        if user is None:
            user_ = user
        else:
            user_ = match_d.get('user') or user
    else:
        shortname = host_shortname(hostname)
        user_ = user

    user_at = user_.strip('@') + '@' if user_ else ''
    domain = config.lab_domain
    if domain and not shortname.endswith('.'):
        domain = '.' + domain
    ret = '{user_at}{short}{domain}'.format(
        user_at=user_at,
        short=shortname,
        domain=domain,
    )
    return ret


def decanonicalize_hostname(hostname):
    lab_domain = ''
    if config.lab_domain:
        lab_domain=r'\.' + config.lab_domain.replace('.', r'\.')
    hostname_expr = hostname_expr_templ.format(lab_domain=lab_domain)
    match = re.match(hostname_expr, hostname)
    if match:
        hostname = match.groupdict()['shortname']
    return hostname


def config_file(string):
    """
    Create a config file

    :param string: name of yaml file used for config.
    :returns: Dictionary of configuration information.
    """
    config_dict = {}
    try:
        with open(string) as f:
            g = yaml.safe_load_all(f)
            for new in g:
                config_dict.update(new)
    except IOError as e:
        raise argparse.ArgumentTypeError(str(e))
    return config_dict


def merge_configs(config_paths) -> dict:
    """ Takes one or many paths to yaml config files and merges them
        together, returning the result.
    """
    conf_dict = dict()
    for conf_path in config_paths:
        if conf_path == "-":
            partial_dict = yaml.safe_load(stdin)
        elif not os.path.exists(conf_path):
            log.debug("The config path {0} does not exist, skipping.".format(conf_path))
            continue
        else:
            with open(conf_path) as partial_file:
                partial_dict: dict = yaml.safe_load(partial_file)
        try:
            conf_dict = deep_merge(conf_dict, partial_dict)
        except Exception:
            # TODO: Should this log as well?
            pprint.pprint("failed to merge {0} into {1}".format(conf_dict, partial_dict))
            raise

    return conf_dict


def get_testdir(ctx=None):
    """
    :param ctx: Unused; accepted for compatibility
    :returns: A test directory
    """
    if 'test_path' in config:
        return config['test_path']
    return config.get(
        'test_path',
        '/home/%s/cephtest' % get_test_user()
    )


def get_test_user(ctx=None):
    """
    :param ctx: Unused; accepted for compatibility
    :returns:   str -- the user to run tests as on remote hosts
    """
    return config.get('test_user', 'ubuntu')


def get_archive_dir(ctx):
    """
    :returns: archive directory (a subdirectory of the test directory)
    """
    test_dir = get_testdir(ctx)
    return os.path.normpath(os.path.join(test_dir, 'archive'))


def get_http_log_path(archive_dir, job_id=None):
    """
    :param archive_dir: directory to be searched
    :param job_id: id of job that terminates the name of the log path
    :returns: http log path
    """
    http_base = config.archive_server
    if not http_base:
        return None

    sep = os.path.sep
    archive_dir = archive_dir.rstrip(sep)
    archive_subdir = archive_dir.split(sep)[-1]
    if archive_subdir.endswith(str(job_id)):
        archive_subdir = archive_dir.split(sep)[-2]

    if job_id is None:
        return os.path.join(http_base, archive_subdir, '')
    return os.path.join(http_base, archive_subdir, str(job_id), '')


def get_results_url(run_name, job_id=None):
    """
    :param run_name: The name of the test run
    :param job_id: The job_id of the job. Optional.
    :returns: URL to the run (or job, if job_id is passed) in the results web
              UI. For example, Inktank uses Pulpito.
    """
    if not config.results_ui_server:
        return None
    base_url = config.results_ui_server

    if job_id is None:
        return os.path.join(base_url, run_name, '')
    return os.path.join(base_url, run_name, str(job_id), '')


def get_ceph_binary_url(package=None,
                        branch=None, tag=None, sha1=None, dist=None,
                        flavor=None, format=None, arch=None):
    """
    return the url of the ceph binary found on gitbuildder.
    """
    BASE = 'http://{host}/{package}-{format}-{dist}-{arch}-{flavor}/'.format(
        host=config.gitbuilder_host,
        package=package,
        flavor=flavor,
        arch=arch,
        format=format,
        dist=dist
    )

    if sha1 is not None:
        assert branch is None, "cannot set both sha1 and branch"
        assert tag is None, "cannot set both sha1 and tag"
    else:
        # gitbuilder uses remote-style ref names for branches, mangled to
        # have underscores instead of slashes; e.g. origin_main
        if tag is not None:
            ref = tag
            assert branch is None, "cannot set both branch and tag"
        else:
            if branch is None:
                branch = 'main'
            ref = branch

        sha1_url = urljoin(BASE, 'ref/{ref}/sha1'.format(ref=ref))
        log.debug('Translating ref to sha1 using url %s', sha1_url)

        try:
            sha1_fp = urlopen(sha1_url)
            sha1 = sha1_fp.read().rstrip('\n')
            sha1_fp.close()
        except HTTPError as e:
            log.error('Failed to get url %s', sha1_url)
            raise e

    log.debug('Using %s %s sha1 %s', package, format, sha1)
    bindir_url = urljoin(BASE, 'sha1/{sha1}/'.format(sha1=sha1))
    return (sha1, bindir_url)


def feed_many_stdins(fp, processes):
    """
    :param fp: input file
    :param processes: list of processes to be written to.
    """
    while True:
        data = fp.read(8192)
        if not data:
            break
        for proc in processes:
            proc.stdin.write(data)


def feed_many_stdins_and_close(fp, processes):
    """
    Feed many and then close processes.

    :param fp: input file
    :param processes: list of processes to be written to.
    """
    feed_many_stdins(fp, processes)
    for proc in processes:
        proc.stdin.close()


def get_mons(roles, ips,
             mon_bind_msgr2=False,
             mon_bind_addrvec=False):
    """
    Get monitors and their associated addresses
    """
    mons = {}
    mon_ports = {}
    mon_id = 0
    is_mon = is_type('mon')
    for idx, roles in enumerate(roles):
        for role in roles:
            if not is_mon(role):
                continue
            if ips[idx] not in mon_ports:
                mon_ports[ips[idx]] = 6789
            else:
                mon_ports[ips[idx]] += 1
            if mon_bind_msgr2:
                assert mon_bind_addrvec
                addr = 'v2:{ip}:{port},v1:{ip}:{port2}'.format(
                    ip=ips[idx],
                    port=mon_ports[ips[idx]],
                    port2=mon_ports[ips[idx]] + 1,
                )
                mon_ports[ips[idx]] += 1
            elif mon_bind_addrvec:
                addr = 'v1:{ip}:{port}'.format(
                    ip=ips[idx],
                    port=mon_ports[ips[idx]],
                )
            else:
                addr = '{ip}:{port}'.format(
                    ip=ips[idx],
                    port=mon_ports[ips[idx]],
                )
            mon_id += 1
            mons[role] = addr
    assert mons
    return mons


def skeleton_config(ctx, roles, ips, cluster='ceph',
                    mon_bind_msgr2=False,
                    mon_bind_addrvec=False):
    """
    Returns a ConfigObj that is prefilled with a skeleton config.

    Use conf[section][key]=value or conf.merge to change it.

    Use conf.write to write it out, override .filename first if you want.
    """
    path = os.path.join(os.path.dirname(__file__), 'ceph.conf.template')
    conf = configobj.ConfigObj(path, file_error=True)
    mons = get_mons(roles=roles, ips=ips,
                    mon_bind_msgr2=mon_bind_msgr2,
                    mon_bind_addrvec=mon_bind_addrvec)
    for role, addr in mons.items():
        mon_cluster, _, _ = split_role(role)
        if mon_cluster != cluster:
            continue
        name = ceph_role(role)
        conf.setdefault(name, {})
        conf[name]['mon addr'] = addr
    # set up standby mds's
    is_mds = is_type('mds', cluster)
    for roles_subset in roles:
        for role in roles_subset:
            if is_mds(role):
                name = ceph_role(role)
                conf.setdefault(name, {})
                if '-s-' in name:
                    standby_mds = name[name.find('-s-') + 3:]
                    conf[name]['mds standby for name'] = standby_mds
    return conf


def ceph_role(role):
    """
    Return the ceph name for the role, without any cluster prefix, e.g. osd.0.
    """
    _, type_, id_ = split_role(role)
    return type_ + '.' + id_


def split_role(role):
    """
    Return a tuple of cluster, type, and id
    If no cluster is included in the role, the default cluster, 'ceph', is used
    """
    cluster = 'ceph'
    if role.count('.') > 1:
        cluster, role = role.split('.', 1)
    type_, id_ = role.split('.', 1)
    return cluster, type_, id_


def roles_of_type(roles_for_host, type_):
    """
    Generator of ids.

    Each call returns the next possible role of the type specified.
    :param roles_for_host: list of roles possible
    :param type_: type of role
    """
    for role in cluster_roles_of_type(roles_for_host, type_, None):
        _, _, id_ = split_role(role)
        yield id_


def cluster_roles_of_type(roles_for_host, type_, cluster):
    """
    Generator of roles.

    Each call returns the next possible role of the type specified.
    :param roles_for_host: list of roles possible
    :param type_: type of role
    :param cluster: cluster name
    """
    is_type_in_cluster = is_type(type_, cluster)
    for role in roles_for_host:
        if not is_type_in_cluster(role):
            continue
        yield role


def all_roles(cluster):
    """
    Generator of role values.  Each call returns another role.

    :param cluster: Cluster extracted from the ctx.
    """
    for _, roles_for_host in cluster.remotes.items():
        for name in roles_for_host:
            yield name


def all_roles_of_type(cluster, type_):
    """
    Generator of role values.  Each call returns another role of the
    type specified.

    :param cluster: Cluster extracted from the ctx.
    :param type_: role type
    """
    for _, roles_for_host in cluster.remotes.items():
        for id_ in roles_of_type(roles_for_host, type_):
            yield id_


def is_type(type_, cluster=None):
    """
    Returns a matcher function for whether role is of type given.

    :param cluster: cluster name to check in matcher (default to no check for cluster)
    """
    def _is_type(role):
        """
        Return type based on the starting role name.

        If there is more than one period, strip the first part
        (ostensibly a cluster name) and check the remainder for the prefix.
        """
        role_cluster, role_type, _ = split_role(role)
        if cluster is not None and role_cluster != cluster:
            return False
        return role_type == type_
    return _is_type


def num_instances_of_type(cluster, type_, ceph_cluster='ceph'):
    """
    Total the number of instances of the role type specified in all remotes.

    :param cluster: Cluster extracted from ctx.
    :param type_: role
    :param ceph_cluster: filter for ceph cluster name
    """
    remotes_and_roles = cluster.remotes.items()
    roles = [roles for (remote, roles) in remotes_and_roles]
    is_ceph_type = is_type(type_, ceph_cluster)
    num = sum(sum(1 for role in hostroles if is_ceph_type(role))
              for hostroles in roles)
    return num


def create_simple_monmap(ctx, remote, conf, path=None,
                         mon_bind_addrvec=False):
    """
    Writes a simple monmap based on current ceph.conf into path, or
    <testdir>/monmap by default.

    Assumes ceph_conf is up to date.

    Assumes mon sections are named "mon.*", with the dot.

    :return the FSID (as a string) of the newly created monmap
    """
    def gen_addresses():
        """
        Monitor address generator.

        Each invocation returns the next monitor address
        """
        for section, data in conf.items():
            PREFIX = 'mon.'
            if not section.startswith(PREFIX):
                continue
            name = section[len(PREFIX):]
            addr = data['mon addr']
            yield (name, addr)

    addresses = list(gen_addresses())
    assert addresses, "There are no monitors in config!"
    log.debug('Ceph mon addresses: %s', addresses)

    testdir = get_testdir(ctx)
    args = [
        'adjust-ulimits',
        'ceph-coverage',
        '{tdir}/archive/coverage'.format(tdir=testdir),
        'monmaptool',
        '--create',
        '--clobber',
    ]
    for (name, addr) in addresses:
        if mon_bind_addrvec:
            args.extend(('--addv', name, addr))
        else:
            args.extend(('--add', name, addr))
    if not path:
        path = '{tdir}/monmap'.format(tdir=testdir)
    args.extend([
        '--print',
        path
    ])

    monmap_output = remote.sh(args)
    fsid = re.search("generated fsid (.+)$",
                     monmap_output, re.MULTILINE).group(1)
    return fsid


def write_file(remote, path, data):
    """
    Write data to a remote file

    :param remote: Remote site.
    :param path: Path on the remote being written to.
    :param data: Data to be written.
    """
    remote.write_file(path, data)


def sudo_write_file(remote, path, data, perms=None, owner=None):
    """
    Write data to a remote file as super user

    :param remote: Remote site.
    :param path: Path on the remote being written to.
    :param data: Data to be written.
    :param perms: Permissions on the file being written
    :param owner: Owner for the file being written

    Both perms and owner are passed directly to chmod.
    """
    remote.sudo_write_file(path, data, mode=perms, owner=owner)


def copy_file(from_remote, from_path, to_remote, to_path=None):
    """
    Copies a file from one remote to another.
    """
    if to_path is None:
        to_path = from_path
    from_remote.run(args=[
        'sudo', 'scp', '-v', from_path, "{host}:{file}".format(
            host=to_remote.name, file=to_path)
    ])


def move_file(remote, from_path, to_path, sudo=False, preserve_perms=True):
    """
    Move a file from one path to another on a remote site

    If preserve_perms is true, the contents of the destination file (to_path,
    which must already exist in this case) are replaced with the contents of the
    source file (from_path) and the permissions of to_path are preserved. If
    preserve_perms is false, to_path does not need to exist, and is simply
    clobbered if it does.
    """
    if preserve_perms:
        args = []
        if sudo:
            args.append('sudo')
        args.extend([
            'stat',
            '-c',
            '\"%a\"',
            to_path
        ])
        perms = remote.sh(args).rstrip().strip('\"')

    args = []
    if sudo:
        args.append('sudo')
    args.extend([
        'mv',
        '--',
        from_path,
        to_path,
    ])
    remote.sh(args)

    if preserve_perms:
        # reset the file back to the original permissions
        args = []
        if sudo:
            args.append('sudo')
        args.extend([
            'chmod',
            perms,
            to_path,
        ])
        remote.sh(args)


def delete_file(remote, path, sudo=False, force=False, check=True):
    """
    rm a file on a remote site. Use force=True if the call should succeed even
    if the file is absent or rm path would otherwise fail.
    """
    args = []
    if sudo:
        args.append('sudo')
    args.extend(['rm'])
    if force:
        args.extend(['-f'])
    args.extend([
        '--',
        path,
    ])
    remote.sh(args, check_status=check)


def remove_lines_from_file(remote, path, line_is_valid_test,
                           string_to_test_for):
    """
    Remove lines from a file.  This involves reading the file in, removing
    the appropriate lines, saving the file, and then replacing the original
    file with the new file.  Intermediate files are used to prevent data loss
    on when the main site goes up and down.
    """
    # read in the specified file
    in_data = remote.read_file(path, False).decode()
    out_data = ""

    first_line = True
    # use the 'line_is_valid_test' function to remove unwanted lines
    for line in in_data.split('\n'):
        if line_is_valid_test(line, string_to_test_for):
            if not first_line:
                out_data += '\n'
            else:
                first_line = False

            out_data += '{line}'.format(line=line)

        else:
            log.info('removing line: {bad_line}'.format(bad_line=line))

    # get a temp file path on the remote host to write to,
    # we don't want to blow away the remote file and then have the
    # network drop out
    temp_file_path = remote.mktemp()

    # write out the data to a temp file
    write_file(remote, temp_file_path, out_data)

    # then do a 'mv' to the actual file location
    move_file(remote, temp_file_path, path)


def append_lines_to_file(remote, path, lines, sudo=False):
    """
    Append lines to a file.
    """
    remote.write_file(path, lines, append=True, sudo=sudo)

def prepend_lines_to_file(remote, path, lines, sudo=False):
    """
    Prepend lines to a file.
    An intermediate file is used in the same manner as in
    Remove_lines_from_list.
    """

    temp_file_path = remote.mktemp()
    remote.write_file(temp_file_path, lines)
    remote.copy_file(path, temp_file_path, append=True, sudo=sudo)
    remote.move_file(temp_file_path, path, sudo=sudo)


def create_file(remote, path, data="", permissions=str(644), sudo=False):
    """
    Create a file on the remote host.
    """
    args = []
    if sudo:
        args.append('sudo')
    args.extend([
        'touch',
        path,
        run.Raw('&&')
    ])
    if sudo:
        args.append('sudo')
    args.extend([
        'chmod',
        permissions,
        '--',
        path
    ])
    remote.sh(args)
    # now write out the data if any was passed in
    if "" != data:
        append_lines_to_file(remote, path, data, sudo)


def get_file(remote, path, sudo=False, dest_dir='/tmp'):
    """
    Get the contents of a remote file. Do not use for large files; use
    Remote.get_file() instead.
    """
    local_path = remote.get_file(path, sudo=sudo, dest_dir=dest_dir)
    with open(local_path, 'rb') as file_obj:
        file_data = file_obj.read()
    os.remove(local_path)
    return file_data


def copy_fileobj(src, tarinfo, local_path):
    with open(local_path, 'wb') as dest:
        shutil.copyfileobj(src, dest)


def pull_directory(remote, remotedir, localdir, write_to=copy_fileobj):
    """
    Copy a remote directory to a local directory.

    :param remote: the remote object representing the remote host from where
                   the specified directory is pulled
    :param remotedir: the source directory on remote host
    :param localdir: the destination directory on localhost
    :param write_to: optional function to write the file to localdir.
                     its signature should be:
                     func(src: fileobj,
                          tarinfo: tarfile.TarInfo,
                          local_path: str)
    """
    log.debug('Transferring archived files from %s:%s to %s',
              remote.shortname, remotedir, localdir)
    if not os.path.exists(localdir):
        os.mkdir(localdir)
    r = remote.get_tar_stream(remotedir, sudo=True, compress=False)
    tar = tarfile.open(mode='r|', fileobj=r.stdout)
    while True:
        ti = tar.next()
        if ti is None:
            break

        if ti.isdir():
            # ignore silently; easier to just create leading dirs below
            # XXX this mean empty dirs are not transferred
            pass
        elif ti.isfile():
            sub = safepath.munge(ti.name)
            safepath.makedirs(root=localdir, path=os.path.dirname(sub))
            with tar.extractfile(ti) as src:
                write_to(src, ti, os.path.join(localdir, sub))
        else:
            if ti.isdev():
                type_ = 'device'
            elif ti.issym():
                type_ = 'symlink'
            elif ti.islnk():
                type_ = 'hard link'
            else:
                type_ = 'unknown'
            log.info('Ignoring tar entry: %r type %r', ti.name, type_)


def pull_directory_tarball(remote, remotedir, localfile):
    """
    Copy a remote directory to a local tarball.
    """
    log.debug('Transferring archived files from %s:%s to %s',
              remote.shortname, remotedir, localfile)
    remote.get_tar(remotedir, localfile, sudo=True)


def get_wwn_id_map(remote, devs):
    log.warning("Entering get_wwn_id_map, a deprecated function that will be removed")
    return dict((d, d) for d in devs)


def get_scratch_devices(remote):
    """
    Read the scratch disk list from remote host
    """
    devs = []
    try:
        file_data = remote.read_file("/scratch_devs").decode()
        devs = file_data.split()
    except Exception:
        devs = remote.sh('ls /dev/[sv]d?').strip().split('\n')

    # Remove root device (vm guests) from the disk list
    for dev in devs:
        if 'vda' in dev:
            devs.remove(dev)
            log.warning("Removing root device: %s from device list" % dev)

    log.debug('devs={d}'.format(d=devs))

    retval = []
    for dev in devs:
        dev_checks = [
            [['stat', dev], "does not exist"],
            [['sudo', 'dd', 'if=%s' % dev, 'of=/dev/null', 'count=1'], "is not readable"],
            [
                [run.Raw('!'), 'mount', run.Raw('|'), 'grep', '-v', 'devtmpfs', run.Raw('|'),
                'grep', '-q', dev],
                "is in use"
            ],
        ]
        for args, msg in dev_checks:
            try:
                remote.run(args=args)
            except CommandFailedError:
                log.debug(f"get_scratch_devices: {dev} {msg}")
                break
        else:
            retval.append(dev)
            continue
        break
    return retval


def wait_until_healthy(ctx, remote, ceph_cluster='ceph', use_sudo=False):
    """
    Wait until a Ceph cluster is healthy. Give up after 15min.
    """
    testdir = get_testdir(ctx)
    # when cluster is setup using ceph-deploy or ansible
    # access to admin key is readonly for ceph user
    cmd = ['ceph', '--cluster', ceph_cluster, 'health']
    if use_sudo:
        cmd.insert(0, 'sudo')
    args = ['adjust-ulimits',
            'ceph-coverage',
            '{tdir}/archive/coverage'.format(tdir=testdir)]
    args.extend(cmd)
    with safe_while(tries=(900 // 6), action="wait_until_healthy") as proceed:
        while proceed():
            out = remote.sh(args, logger=log.getChild('health'))
            log.debug('Ceph health: %s', out.rstrip('\n'))
            if out.split(None, 1)[0] == 'HEALTH_OK':
                break
            time.sleep(1)


def wait_until_osds_up(ctx, cluster, remote, ceph_cluster='ceph'):
    """Wait until all Ceph OSDs are booted."""
    num_osds = num_instances_of_type(cluster, 'osd', ceph_cluster)
    testdir = get_testdir(ctx)
    with safe_while(sleep=6, tries=90) as proceed:
        while proceed():
            daemons = ctx.daemons.iter_daemons_of_role('osd', ceph_cluster)
            for daemon in daemons:
                daemon.check_status()
            out = remote.sh(
                [
                    'adjust-ulimits',
                    'ceph-coverage',
                    '{tdir}/archive/coverage'.format(tdir=testdir),
                    'ceph',
                    '--cluster', ceph_cluster,
                    'osd', 'dump', '--format=json'
                ],
                logger=log.getChild('health'),
            )
            j = json.loads('\n'.join(out.split('\n')[1:]))
            up = sum(1 for o in j['osds'] if 'up' in o['state'])
            log.debug('%d of %d OSDs are up' % (up, num_osds))
            if up == num_osds:
                break


def reboot(node, timeout=300, interval=30):
    """
    Reboots a given system, then waits for it to come back up and
    re-establishes the ssh connection.

    :param node: The teuthology.orchestra.remote.Remote object of the node
    :param timeout: The amount of time, in seconds, after which to give up
                    waiting for the node to return
    :param interval: The amount of time, in seconds, to wait between attempts
                     to re-establish with the node. This should not be set to
                     less than maybe 10, to make sure the node actually goes
                     down first.
    """
    log.info("Rebooting {host}...".format(host=node.hostname))
    node.run(args=['sudo', 'shutdown', '-r', 'now'])
    reboot_start_time = time.time()
    while time.time() - reboot_start_time < timeout:
        time.sleep(interval)
        if node.is_online or node.reconnect():
            return
    raise RuntimeError(
        "{host} did not come up after reboot within {time}s".format(
            host=node.hostname, time=timeout))


def reconnect(ctx, timeout, remotes=None):
    """
    Connect to all the machines in ctx.cluster.

    Presumably, some of them won't be up. Handle this
    by waiting for them, unless the wait time exceeds
    the specified timeout.

    ctx needs to contain the cluster of machines you
    wish it to try and connect to, as well as a config
    holding the ssh keys for each of them. As long as it
    contains this data, you can construct a context
    that is a subset of your full cluster.
    """
    log.info('Re-opening connections...')
    starttime = time.time()

    if remotes:
        need_reconnect = remotes
    else:
        need_reconnect = list(ctx.cluster.remotes.keys())

    while need_reconnect:
        for remote in need_reconnect:
            log.info('trying to connect to %s', remote.name)
            success = remote.reconnect()
            if not success:
                if time.time() - starttime > timeout:
                    raise RuntimeError("Could not reconnect to %s" %
                                       remote.name)
            else:
                need_reconnect.remove(remote)

        log.debug('waited {elapsed}'.format(
            elapsed=str(time.time() - starttime)))
        time.sleep(1)


def get_clients(ctx, roles):
    """
    return all remote roles that are clients.
    """
    for role in roles:
        assert isinstance(role, str)
        assert 'client.' in role
        _, _, id_ = split_role(role)
        (remote,) = ctx.cluster.only(role).remotes.keys()
        yield (id_, remote)


def get_user():
    """
    Return the username in the format user@host.
    """
    return getpass.getuser() + '@' + socket.gethostname()


def get_mon_names(ctx, cluster='ceph'):
    """
    :returns: a list of monitor names
    """
    is_mon = is_type('mon', cluster)
    host_mons = [[role for role in roles if is_mon(role)]
                 for roles in ctx.cluster.remotes.values()]
    return [mon for mons in host_mons for mon in mons]


def get_first_mon(ctx, config, cluster='ceph'):
    """
    return the "first" mon role (alphanumerically, for lack of anything better)
    """
    mons = get_mon_names(ctx, cluster)
    if mons:
        return sorted(mons)[0]
    assert False, 'no mon for cluster found'


def replace_all_with_clients(cluster, config):
    """
    Converts a dict containing a key all to one
    mapping all clients to the value of config['all']
    """
    assert isinstance(config, dict), 'config must be a dict'
    if 'all' not in config:
        return config
    norm_config = {}
    assert len(config) == 1, \
        "config cannot have 'all' and specific clients listed"
    for client in all_roles_of_type(cluster, 'client'):
        norm_config['client.{id}'.format(id=client)] = config['all']
    return norm_config


DeepMerge = TypeVar('DeepMerge')
def deep_merge(a: DeepMerge, b: DeepMerge) -> DeepMerge:
    """
    Deep Merge.  If a and b are both lists, all elements in b are
    added into a.  If a and b are both dictionaries, elements in b are
    recursively added to a.
    :param a: object items will be merged into
    :param b: object items will be merged from
    """
    if b is None:
        return a
    if a is None:
        return deep_merge(b.__class__(), b)
    if isinstance(a, list):
        assert isinstance(b, list)
        a.extend(b)
        return a
    if isinstance(a, dict):
        assert isinstance(b, dict)
        for (k, v) in b.items():
            a[k] = deep_merge(a.get(k), v)
        return a
    return b

def update_key(key_to_update, a: dict, b: dict):
    """
    Update key (`key_to_update`) of dict `a` on all levels
    to the values of same key in `b` dict.
    """
    for key, value in b.items():
        if key == key_to_update:
            a[key] = value
        elif isinstance(value, dict):
            if key in a and isinstance(a[key], dict):
                update_key(key_to_update, a[key], value)

def ssh_keyscan(hostnames, _raise=True):
    """
    Fetch the SSH public key of one or more hosts

    :param hostnames: A list of hostnames, or a dict keyed by hostname
    :param _raise: Whether to raise an exception if not all keys are retrieved
    :returns: A dict keyed by hostname, with the host keys as values
    """
    if not isinstance(hostnames, list) and not isinstance(hostnames, dict):
        raise TypeError("'hostnames' must be a list")
    hostnames = [canonicalize_hostname(name, user=None) for name in
                 hostnames]
    keys_dict = dict()
    for hostname in hostnames:
        with safe_while(
            sleep=1,
            tries=15 if _raise else 1,
            increment=1,
            _raise=_raise,
            action="ssh_keyscan " + hostname,
        ) as proceed:
            while proceed():
                key = _ssh_keyscan(hostname)
                if key:
                    keys_dict[hostname] = key
                    break
    if len(keys_dict) != len(hostnames):
        missing = set(hostnames) - set(keys_dict.keys())
        msg = "Unable to scan these host keys: %s" % ' '.join(missing)
        if not _raise:
            log.warning(msg)
        else:
            raise RuntimeError(msg)
    return keys_dict


def _ssh_keyscan(hostname):
    """
    Fetch the SSH public key of one or more hosts

    :param hostname: The hostname
    :returns: The host key
    """
    args = ['ssh-keyscan', '-T', '1', hostname]
    if config.tunnel:
        for tunnel in config.tunnel:
            if hostname in tunnel.get('hosts'):
                bastion = tunnel.get('bastion')
                args = ['ssh', bastion.get('host')] + args
    p = subprocess.Popen(
        args=args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    p.wait()
    for line in p.stderr:
        line = line.decode()
        line = line.strip()
        if line and not line.startswith('#'):
            log.error(line)
    keys = list()
    for line in p.stdout:
        host, key = line.strip().decode().split(' ', 1)
        keys.append(key)
    if len(keys) > 0:
        return sorted(keys)[0]


def ssh_keyscan_wait(hostname):
    """
    Run ssh-keyscan against a host, return True if it succeeds,
    False otherwise. Try again if ssh-keyscan timesout.
    :param hostname: on which ssh-keyscan is run
    """
    with safe_while(sleep=6, tries=100, _raise=False,
                    action="ssh_keyscan_wait " + hostname) as proceed:
        success = False
        while proceed():
            key = _ssh_keyscan(hostname)
            if key:
                success = True
                break
            log.info("try ssh_keyscan again for " + str(hostname))
        return success

def stop_daemons_of_type(ctx, type_, cluster='ceph', timeout=300):
    """
    :param type_: type of daemons to be stopped.
    :param cluster: Cluster name, default is 'ceph'.
    :param timeout: Timeout in seconds for stopping each daemon.
    """
    log.info('Shutting down %s daemons...' % type_)
    exc = None
    for daemon in ctx.daemons.iter_daemons_of_role(type_, cluster):
        try:
            daemon.stop(timeout)
        except (CommandFailedError,
                CommandCrashedError,
                ConnectionLostError) as e:
            exc = e
            log.exception('Saw exception from %s.%s', daemon.role, daemon.id_)
    if exc is not None:
        raise exc


def get_system_type(remote, distro=False, version=False):
    """
    If distro, return distro.
    If version, return version
    If both, return both.
    If neither, return 'deb' or 'rpm' if distro is known to be one of those
    """
    if version:
        version = remote.os.version
    if distro and version:
        return remote.os.name, version
    if distro:
        return remote.os.name
    if version:
        return version
    return remote.os.package_type

def get_pkg_type(os_type):
    if os_type in ('centos', 'fedora', 'opensuse', 'rhel', 'sle'):
        return 'rpm'
    else:
        return 'deb'

def get_distro(ctx):
    """
    Get the name of the distro that we are using (usually the os_type).
    """
    os_type = None
    if ctx.os_type:
        return ctx.os_type

    try:
        os_type = ctx.config.get('os_type', None)
    except AttributeError:
        pass

    # if os_type is None, return the default of ubuntu
    return os_type or "ubuntu"


def get_distro_version(ctx):
    """
    Get the verstion of the distro that we are using (release number).
    """
    distro = get_distro(ctx)
    if ctx.os_version is not None:
        return str(ctx.os_version)
    try:
        os_version = ctx.config.get('os_version', DEFAULT_OS_VERSION[distro])
    except AttributeError:
        os_version = DEFAULT_OS_VERSION[distro]
    return str(os_version)


def get_multi_machine_types(machinetype):
    """
    Converts machine type string to list based on common deliminators
    """
    machinetypes = []
    machine_type_deliminator = [',', ' ', '\t']
    for deliminator in machine_type_deliminator:
        if deliminator in machinetype:
            machinetypes = machinetype.split(deliminator)
            break
    if not machinetypes:
        machinetypes.append(machinetype)
    return machinetypes


def is_in_dict(searchkey, searchval, d):
    """
    Test if searchkey/searchval are in dictionary.  searchval may
    itself be a dict, in which case, recurse.  searchval may be
    a subset at any nesting level (that is, all subkeys in searchval
    must be found in d at the same level/nest position, but searchval
    is not required to fully comprise d[searchkey]).

    >>> is_in_dict('a', 'foo', {'a':'foo', 'b':'bar'})
    True

    >>> is_in_dict(
    ...     'a',
    ...     {'sub1':'key1', 'sub2':'key2'},
    ...     {'a':{'sub1':'key1', 'sub2':'key2', 'sub3':'key3'}}
    ... )
    True

    >>> is_in_dict('a', 'foo', {'a':'bar', 'b':'foo'})
    False

    >>> is_in_dict('a', 'foo', {'a':{'a': 'foo'}})
    False
    """
    val = d.get(searchkey, None)
    if isinstance(val, dict) and isinstance(searchval, dict):
        for foundkey, foundval in searchval.items():
            if not is_in_dict(foundkey, foundval, val):
                return False
        return True
    else:
        return searchval == val


def sh(command, log_limit=1024, cwd=None, env=None):
    """
    Run the shell command and return the output in ascii (stderr and
    stdout).  If the command fails, raise an exception. The command
    and its output are logged, on success and on error.
    """
    log.debug(":sh: " + command)
    proc = subprocess.Popen(
        args=command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True,
        bufsize=1)
    lines = []
    truncated = False
    with proc.stdout:
        for line in proc.stdout:
            line = line.decode()
            lines.append(line)
            line = line.rstrip()
            if len(line) > log_limit:
                truncated = True
                log.debug(line[:log_limit] +
                          "... (truncated to the first " + str(log_limit) +
                          " characters)")
            else:
                log.debug(line)
    output = "".join(lines)
    if proc.wait() != 0:
        if truncated:
            log.error(command + " replay full stdout/stderr"
                      " because an error occurred and some of"
                      " it was truncated")
            log.error(output)
        raise subprocess.CalledProcessError(
            returncode=proc.returncode,
            cmd=command,
            output=output
        )
    return output


def add_remote_path(ctx, local_dir, remote_dir):
    """
    Add key/value pair (local_dir: remote_dir) to job's info.yaml.
    These key/value pairs are read to archive them in case of job timeout.
    """
    if ctx.archive is None:
        return
    with open(os.path.join(ctx.archive, 'info.yaml'), 'r+') as info_file:
        info_yaml = yaml.safe_load(info_file)
        info_file.seek(0)
        if 'archive' in info_yaml:
            info_yaml['archive'][local_dir] = remote_dir
        else:
            info_yaml['archive'] = {local_dir: remote_dir}
        yaml.safe_dump(info_yaml, info_file, default_flow_style=False)


def archive_logs(ctx, remote_path, log_path):
    """
    Archive directories from all nodes in a cliuster. It pulls all files in
    remote_path dir to job's archive dir under log_path dir.
    """
    if ctx.archive is None:
        return
    path = os.path.join(ctx.archive, 'remote')
    os.makedirs(path, exist_ok=True)
    for remote in ctx.cluster.remotes.keys():
        sub = os.path.join(path, remote.shortname)
        os.makedirs(sub, exist_ok=True)
        try:
            pull_directory(remote, remote_path, os.path.join(sub, log_path))
        except ReadError:
            pass


def compress_logs(ctx, remote_dir):
    """
    Compress all files in remote_dir from all nodes in a cluster.
    """
    log.info('Compressing logs...')
    run.wait(
        ctx.cluster.run(
            args=(f"sudo find {remote_dir} -name *.log -print0 | "
                  f"sudo xargs --max-args=1 --max-procs=0 --verbose -0 --no-run-if-empty -- gzip -5 --verbose --"),
            wait=False,
        ),
    )
