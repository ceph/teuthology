"""
SSH helper utilities for teuthology.

This module provides functions for working with SSH host keys, including:
- Scanning SSH host keys from remote hosts
- Waiting for SSH services to become available
- Handling SSH key retrieval with retries

These functions are used during host provisioning and setup to ensure
SSH connectivity is properly established before running tests.
"""
import logging
import subprocess

from teuthology.contextutil import safe_while
from teuthology.util.hostname import canonicalize_hostname


log = logging.getLogger(__name__)


def _ssh_keyscan(hostname):
    """
    Fetch the SSH public key of a single host using ssh-keyscan.
    
    This is an internal helper function that performs a single ssh-keyscan
    attempt without retries.
    
    :param hostname: The hostname to scan
    :returns: The host key, or None if the scan failed
    """
    args = ['ssh-keyscan', '-T', '1', hostname]
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


def ssh_keyscan(hostnames, _raise=True):
    """
    Fetch the SSH public keys of one or more hosts.
    
    This function scans SSH host keys from multiple hosts, with automatic
    retries for failed scans. It canonicalizes hostnames before scanning.
    
    :param hostnames: A list of hostnames, or a dict keyed by hostname
    :param _raise: Whether to raise an exception if not all keys are retrieved
    :returns: A dict keyed by hostname, with the host keys as values
    :raises TypeError: If hostnames is not a list or dict
    :raises RuntimeError: If _raise is True and not all keys could be retrieved
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


def ssh_keyscan_wait(hostname):
    """
    Wait for SSH to become available on a host by repeatedly scanning for its key.
    
    This function repeatedly attempts to scan the SSH host key until it succeeds
    or the maximum number of retries is reached. It's useful when waiting for
    a host to finish booting or for SSH to start.
    
    :param hostname: The hostname to scan
    :returns: True if the key was successfully retrieved, False otherwise
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

# Made with Bob
