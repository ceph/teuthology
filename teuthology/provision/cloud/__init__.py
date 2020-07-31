import logging

from teuthology.config import config

from teuthology.provision.cloud import openstack

log = logging.getLogger(__name__)


supported_drivers = dict(
    openstack=dict(
        provider=openstack.OpenStackProvider,
        provisioner=openstack.OpenStackProvisioner,
        rh_provider=openstack.RHOpenStackProvider,
        rh_provisioner=openstack.RHOpenStackProvisioner
    ),
)


def get_types():
    types = list()
    if 'libcloud' in config and 'providers' in config.libcloud:
        types = list(config.libcloud['providers'].keys())
    return types


def get_provider_conf(node_type):
    all_providers = config.libcloud['providers']
    provider_conf = all_providers[node_type]
    return provider_conf


def get_provider(node_type):
    provider_conf = get_provider_conf(node_type)
    driver = provider_conf['driver']
    provider_cls = supported_drivers[driver]['provider']
    if provider_conf.get('driver_args', {}).get('ex_domain_name') == 'redhat.com':
        provider_cls = supported_drivers[driver]['rh_provider']
    return provider_cls(name=node_type, conf=provider_conf)


def get_provisioner(node_type, name, os_type, os_version, conf=None):
    provider = get_provider(node_type)
    provider_conf = get_provider_conf(node_type)
    driver = provider_conf['driver']
    provisioner_cls = supported_drivers[driver]['provisioner']
    if provider_conf.get('driver_args', {}).get('ex_domain_name') == 'redhat.com':
        provisioner_cls = supported_drivers[driver]['rh_provisioner']
    return provisioner_cls(
        provider=provider,
        name=name,
        os_type=os_type,
        os_version=os_version,
        conf=conf,
    )
