import subprocess
import os
import yaml
import httplib2
import logging
import tempfile
import re

from . import lockstatus as ls
from . import misc

log = logging.getLogger(__name__)

def decanonicalize_hostname(s):
    if re.match('ubuntu@.*\.front\.sepia\.ceph\.com', s):
        s = s[len('ubuntu@'): -len('.front.sepia.ceph.com')]
    return s

def _get_downburst_exec():
    """
    First check for downburst in the user's path.
    Then check in ~/src, ~ubuntu/src, and ~teuthology/src.
    Return '' if no executable downburst is found.
    """
    path = os.environ.get('PATH', None)
    if path:
        for p in os.environ.get('PATH', '').split(os.pathsep):
            pth = os.path.join(p, 'downburst')
            if os.access(pth, os.X_OK):
                return pth
    import pwd
    little_old_me = pwd.getpwuid(os.getuid()).pw_name
    for user in [little_old_me, 'ubuntu', 'teuthology']:
        pth = "/home/%s/src/downburst/virtualenv/bin/downburst" % user
        if os.access(pth, os.X_OK):
            return pth
    return ''

#
# Use downburst to create a virtual machine
#


def create_if_vm(ctx, machine_name):
    status_info = ls.get_status(ctx, machine_name)
    phys_host = status_info['vpshost']
    if not phys_host:
        return False
    os_type = misc.get_distro(ctx)
    os_version = misc.get_distro_version(ctx)

    createMe = decanonicalize_hostname(machine_name)
    with tempfile.NamedTemporaryFile() as tmp:
        try:
            lfile = ctx.downburst_conf
            with open(lfile) as downb_yaml:
                lcnfg = yaml.safe_load(downb_yaml)
                if lcnfg.keys() == ['downburst']:
                    lcnfg = lcnfg['downburst']
        except (TypeError, AttributeError):
            try:
                lcnfg = {}
                for tdict in ctx.config['downburst']:
                    for key in tdict:
                        lcnfg[key] = tdict[key]
            except (KeyError, AttributeError):
                lcnfg = {}
        except IOError:
            print "Error reading %s" % lfile
            return False

        distro = lcnfg.get('distro', os_type.lower())
        distroversion = lcnfg.get('distroversion', os_version)

        file_info = {}
        file_info['disk-size'] = lcnfg.get('disk-size', '30G')
        file_info['ram'] = lcnfg.get('ram', '1.9G')
        file_info['cpus'] = lcnfg.get('cpus', 1)
        file_info['networks'] = lcnfg.get('networks',
                 [{'source': 'front', 'mac': status_info['mac']}])
        file_info['distro'] = distro
        file_info['distroversion'] = distroversion
        file_info['additional-disks'] = lcnfg.get(
            'additional-disks', 3)
        file_info['additional-disks-size'] = lcnfg.get(
            'additional-disks-size', '200G')
        file_info['arch'] = lcnfg.get('arch', 'x86_64')
        file_out = {'downburst': file_info}
        yaml.safe_dump(file_out, tmp)
        metadata = "--meta-data=%s" % tmp.name
        dbrst = _get_downburst_exec()
        if not dbrst:
            log.error("No downburst executable found.")
            return False
        p = subprocess.Popen([dbrst, '-c', phys_host,
                              'create', metadata, createMe],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,)
        owt, err = p.communicate()
        if err:
            log.info("Downburst completed on %s: %s" %
                    (machine_name, err))
        else:
            log.info("%s created: %s" % (machine_name, owt))
        # If the guest already exists first destroy then re-create:
        if 'exists' in err:
            log.info("Guest files exist. Re-creating guest: %s" %
                    (machine_name))
            destroy_if_vm(ctx, machine_name)
            create_if_vm(ctx, machine_name)
    return True
#
# Use downburst to destroy a virtual machine
#


def destroy_if_vm(ctx, machine_name):
    """
    Return False only on vm downburst failures.
    """
    status_info = ls.get_status(ctx, machine_name)
    phys_host = status_info['vpshost']
    if not phys_host:
        return True
    destroyMe = decanonicalize_hostname(machine_name)
    dbrst = _get_downburst_exec()
    if not dbrst:
        log.error("No downburst executable found.")
        return False
    p = subprocess.Popen([dbrst, '-c', phys_host,
                          'destroy', destroyMe],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,)
    owt, err = p.communicate()
    if err:
        log.error(err)
        return False
    else:
        log.info("%s destroyed: %s" % (machine_name, owt))
    return True


#
# Set machine's cobbler profile and enable PXE.
#
def set_cobbler_profile(profile, servername, dist, release, cobbler_url):
    #Set Profile:
    err_msg = 'Cobbler Failed to change server: {servername} to profile: {profile}'.format(servername=servername, profile=profile)
    cobbler_request(cobbler_url + "/svc/op/changeprofile/system/" + servername + "/profile/" + profile, err_msg)

    #Enable PXE
    err_msg = 'Cobbler Failed to enable PXE for server: {servername}'.format(servername=servername)
    cobbler_request(cobbler_url + "/svc/op/dopxe/system/" + servername, err_msg)

    log.info('Imaging of server: {server} from: {dist}-{release} using cobbler profile: {profile}'.format(
        server=servername, dist=dist, release=release, profile=profile)) 

#
# Find cobbler profile from os type, verison, arch.
#
def find_cobbler_profile(os_type, os_version, os_arch, cobbler_url):
    # Get list of common archs from standardized name
    archs = misc.resolve_equivalent_arch(os_arch)

    # Grab list of available profiles from cobbler server
    profiles = cobbler_request(cobbler_url + "/svc/op/list/what/profiles").strip('\n').split()

    for profile in profiles:
        # Skip profiles with vserver or vercoi in their names, vserver images
        if 'vserver' in profile:
            continue
        if 'vercoi' in profile:
            continue

        # Search for profile in profile list.
        if os_type in profile:
            if os_version in profile:
                for arch in archs:
                    if arch in profile:
                        return profile

    raise Exception('Unable to find distro in Cobbler Profiles')

#
# Check current OS/version and re-image if wrong.
#
def reimage_if_wrong_os(ctx, machine_name, machine_type, dist, release):
    # This is for baremetal so ignore VPS
    if machine_type == 'vps':
        return False
    servername = decanonicalize_hostname(machine_name)
    os_type = misc.get_distro(ctx)

    # Dictionray of default versions if not specified.
    default_os_version = dict(
        ubuntu="12.04",
        fedora="18",
        centos="6.4",
        opensuse="12.2",
        sles="11-sp2",
        rhel="6.4",
        debian='7.0'
        )

    # Try to grab os version or default from dict if it fails.
    try:
        os_version = ctx.config.get('os_version', default_os_version[os_type])
    except AttributeError:
        os_version = default_os_version[os_type]

    # Try to grab os arch or default of x86_64.
    try:
        os_arch = ctx.config.get('os_arch', 'x86_64')
    except AttributeError:
        os_arch = 'x86_64'

    # Allow other common writings for arch.
    os_arch = misc.resolve_equivalent_arch(os_arch, reverse=True)

    # Check if machine is already the requested os/version.
    if dist in os_type:
       if release in os_version:
           return False

    # Find cobbler profile for re-image, set, and reboot
    cobbler_url = ctx.teuthology_config.get('cobbler_url', 'http://plana01.front.sepia.ceph.com/cblr')
    profile = find_cobbler_profile(os_type, os_version, os_arch, cobbler_url)
    set_cobbler_profile(profile, servername, dist, release, cobbler_url)
    return True

#
# Helper for interactig with cobbler.
#
def cobbler_request(url, err_msg='Unknown Error'):
    http = httplib2.Http()
    # Send Get request to server.
    resp, content = http.request(url, "GET")
    succeeded = content.strip('\n')
    status = resp['status']
    # What queries to cobbler returns data instead of a True/False suceeded message.
    if 'what' not in url:
        if succeeded  != 'True':
            raise Exception(err_msg)
    if status != '200':
        raise Exception('Received non 200 HTTP response code: {status}'.format(status=status))
    return content
