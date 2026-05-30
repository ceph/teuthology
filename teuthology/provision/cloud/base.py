import logging
from copy import deepcopy
from typing import List, Optional

from libcloud.compute.providers import get_driver
from libcloud.compute.types import Provider as lc_Provider

import teuthology.orchestra.remote
import teuthology.provision.cloud
from teuthology.misc import canonicalize_hostname, decanonicalize_hostname

log = logging.getLogger(__name__)


class Provider(object):
    _driver_posargs: List[str] = []

    def __init__(self, name: str, conf: dict) -> None:
        self.name = name
        self.conf = conf
        self.driver_name = self.conf['driver']

    def _get_driver(self):
        driver_type = get_driver(
            getattr(lc_Provider, self.driver_name.upper())
        )
        driver_args = self._get_driver_args()
        driver = driver_type(
            *[driver_args.pop(arg_name) for arg_name in self._driver_posargs],
            **driver_args
        )
        return driver
    driver = property(fget=_get_driver)

    def _get_driver_args(self) -> dict:
        return deepcopy(self.conf['driver_args'])


class Provisioner(object):
    def __init__(
        self,
        provider: Provider | str,
        name: str,
        os_type: Optional[str] = None,
        os_version: Optional[str] = None,
        conf: Optional[dict] = None,
        user: str = 'ubuntu',
    ) -> None:
        if isinstance(provider, str):
            provider = teuthology.provision.cloud.get_provider(provider)
        self.provider = provider
        self.name = decanonicalize_hostname(name)
        self.hostname = canonicalize_hostname(name, user=None)
        self.os_type = os_type
        self.os_version = os_version
        self.user = user

    def create(self) -> bool:
        try:
            return self._create()
        except Exception:
            log.exception("Failed to create %s", self.name)
            return False

    def _create(self):
        pass

    def destroy(self) -> bool:
        try:
            return self._destroy()
        except Exception:
            log.exception("Failed to destroy %s", self.name)
            return False

    def _destroy(self):
        pass

    @property
    def remote(self):
        if not hasattr(self, '_remote'):
            self._remote = teuthology.orchestra.remote.Remote(
                "%s@%s" % (self.user, self.name),
            )
        return self._remote

    def __repr__(self) -> str:
        template = "%s(provider='%s', name='%s', os_type='%s', " \
            "os_version='%s')"
        return template % (
            self.__class__.__name__,
            self.provider.name,
            self.name,
            self.os_type,
            self.os_version,
        )
