"""
Hostname utility functions for teuthology.

This module provides functions for working with hostnames, including:
- Converting hostnames to short names
- Canonicalizing hostnames with lab domain and user information
- Decanonicalize hostnames by removing lab domain

These functions handle both regular hostnames and IP addresses (IPv4 and IPv6).
"""
import re
from typing import Optional

from netaddr.strategy.ipv4 import valid_str as _is_ipv4
from netaddr.strategy.ipv6 import valid_str as _is_ipv6

from teuthology.config import config


hostname_expr_templ = '(?P<user>.*@)?(?P<shortname>.*){lab_domain}'


def host_shortname(hostname):
    """
    Extract the short name from a hostname.
    
    For IP addresses (IPv4 or IPv6), returns the address unchanged.
    For hostnames, returns everything before the first dot.
    
    :param hostname: The hostname or IP address
    :returns: The short hostname or IP address
    """
    if _is_ipv4(hostname) or _is_ipv6(hostname):
        return hostname
    else:
        return hostname.split('.', 1)[0]


def canonicalize_hostname(hostname, user: Optional[str] = 'ubuntu'):
    """
    Convert a hostname to its canonical form with user and lab domain.
    
    This function takes a hostname (which may or may not include a user prefix
    and/or lab domain) and returns it in canonical form: user@shortname.lab_domain
    
    For IP addresses, returns user@ip_address format.
    
    :param hostname: The hostname to canonicalize
    :param user: The default user to use if not specified in hostname (default: 'ubuntu')
    :returns: The canonicalized hostname in the form user@shortname.lab_domain
    """
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
    """
    Remove the lab domain from a hostname, leaving just the short name.
    
    This function strips the user prefix (if present) and lab domain suffix
    from a hostname, returning just the short hostname.
    
    :param hostname: The hostname to decanonicalize
    :returns: The short hostname without user prefix or lab domain
    """
    lab_domain = ''
    if config.lab_domain:
        lab_domain = r'\.' + config.lab_domain.replace('.', r'\.')
    hostname_expr = hostname_expr_templ.format(lab_domain=lab_domain)
    match = re.match(hostname_expr, hostname)
    if match:
        hostname = match.groupdict()['shortname']
    return hostname

# Made with Bob
