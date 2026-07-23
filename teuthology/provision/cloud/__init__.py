import logging
from typing import List, Optional, Type, TypedDict

from teuthology.config import config

from teuthology.provision.cloud import base, openstack

log = logging.getLogger(__name__)

class SupportedDrivers(TypedDict):
    provider: Type[base.Provider]
    provisioner: Type[base.Provisioner]

supported_drivers: dict[str, SupportedDrivers] = dict(
    openstack=dict(
        provider=openstack.OpenStackProvider,
        provisioner=openstack.OpenStackProvisioner,
    ),
)


def get_types() -> List[str]:
    types = list()
    if 'libcloud' in config and 'providers' in config.libcloud:
        types = list(config.libcloud['providers'].keys())
    return types


def get_provider_conf(node_type: str) -> dict:
    all_providers = config.libcloud['providers']
    provider_conf = all_providers[node_type]
    return provider_conf


def get_provider(node_type: str):
    provider_conf = get_provider_conf(node_type)
    driver = provider_conf['driver']
    provider_cls: Type[base.Provider] = supported_drivers[driver]['provider']
    return provider_cls(name=node_type, conf=provider_conf)


def get_provisioner(
    node_type: str,
    name: str,
    os_type: Optional[str],
    os_version: Optional[str],
    conf: Optional[dict] = None
):
    provider = get_provider(node_type)
    provider_conf = get_provider_conf(node_type)
    driver = provider_conf['driver']
    provisioner_cls = supported_drivers[driver]['provisioner']
    # Dynamic class lookup - type checker can't verify the correct signature
    return provisioner_cls(
        provider=provider,
        name=name,
        os_type=os_type,
        os_version=os_version,
        conf=conf or {},
    )
