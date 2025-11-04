import io
import json
import logging

from oauthlib.oauth1 import SIGNATURE_PLAINTEXT
from requests import Response
from requests_oauthlib import OAuth1Session
from typing import Any, Dict, List, Optional, Union, Tuple

import teuthology.orchestra

from teuthology.config import config
from teuthology.contextutil import safe_while
from teuthology.orchestra.opsys import OS
from teuthology import misc

log = logging.getLogger(__name__)


def enabled(warn: bool = False) -> bool:
    """Check for required MAAS settings

    :param warn: Whether to log a message containing unset parameters

    :returns: True if all required settings are present; False otherwise
    """
    maas_conf = config.get("maas", {})
    params: List[str] = ["api_url", "api_key", "machine_types"]
    unset = [param for param in params if not maas_conf.get(param)]
    
    if unset and warn:
        log.warning(
            "MAAS disabled; set the following config options to enable: %s",
            " ".join(unset)
        )

    if unset:
        if not config.get("maas", {}).get("api_url"):
            return False

        api_key = config.get("maas", {}).get("api_key")
        if not api_key:
            return False
        if len(api_key.split(":")) < 3:
            log.warning(
                "MAAS api_key appears to be malformed; expected format is "
                "'consumer_key:consumer_token:secret'"
            )
            return False

    return True

def get_types() -> List[str]:
    """Fetch and parse MAAS machine_types config.

    :returns: The list of MAAS-configured machine types.
                Returns an empty list if MAAS is not configured
    """
    if not enabled():
        return []
    maas_conf = config.get("maas", {})
    types = maas_conf.get("machine_types", "")
    if not isinstance(types, list):
        types = types.split(",")
    return [type_ for type_ in types if type_]


def get_session() -> OAuth1Session:
    """Create an OAuth1Session for communicating with the MAAS server
    
    :returns: OAuth1Session: An authenticated session object configured with the
                MAAS API key credentials
    """
    if not enabled():
        raise RuntimeError("MAAS is not configured!")

    key, token, secret = config.maas["api_key"].split(":")
    return OAuth1Session(
        key,
        resource_owner_key=token,
        resource_owner_secret=secret,
        signature_method=SIGNATURE_PLAINTEXT
    )


class MAAS(object):
    """Reimage machines with https://maas.io"""

    def __init__(
            self, name: str, os_type: Optional[str] = None, os_version: Optional[str] = None
        ) -> None:
        """Initialize the MAAS object

        :param name: The fully-qualified domain name of the machine to manage
        :param os_type: The OS type to deploy (e.g. "ubuntu")
        :param os_version: The OS version to deploy (e.g. "22.04")
        """
        self.session = get_session()

        self.remote = teuthology.orchestra.remote.Remote(misc.canonicalize_hostname(name))
        self.name = self.remote.hostname
        self.shortname = self.remote.shortname

        self.log = log.getChild(self.shortname)

        self.os_type, self.os_version, self.system_id = self._get_system_info()
        if (self.os_type, self.os_version, os_type, os_version).count(None) == 4:
            raise RuntimeError(f"Unable to find OS details for machine {name}")

        if ((os_type and os_version) and
                (self.os_type, self.os_version) != (os_type, os_version)):
            log.warning(
                "User provided %s, %s and machine %s, %s os details are not matching",
                os_type, os_version, self.os_type, self.os_version
            )
            self.os_type, self.os_version = os_type, os_version

    def _get_system_info(self) -> Tuple[Optional[str], Optional[str], str]:
        """Get the system info for the deployed machine

        :returns: A tuple (os_type, os_version, system_id)
                    For machines in 'Ready' state, os_type and os_version will be None
        """
        machine = self.get_machines_data()
        status_name = machine.get("status_name", "").lower()
        if status_name == "ready":
            return None, None, machine.get("system_id")

        if status_name in ["deployed", "allocated"]:
            os_type = machine.get("osystem", "").lower()
            os_version = OS._codename_to_version(
                os_type, machine.get("distro_series")
            )
            return os_type, os_version, machine.get("system_id")

        raise RuntimeError(
            "MaaS machine %s is not Ready or Deployed, current status is %s",
            self.shortname, status_name
        )

    def do_request(
        self,
        path: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], list]] = None,
        files: Optional[Dict[str, Any]] = None,
        raise_on_error: bool = True
    ) -> Response:
        """Submit a request to the MAAS server

        :param path: The path of the URL to append to the endpoint, e.g. "/machines/"
        :param method: The HTTP method to use for the request (default: "GET")
        :param params: Optional query or operation parameters to submit with the request
        :param data: Optional JSON data to submit with the request
        :param files: Optional file data to submit with the request
        :param raise_on_error: Whether to raise an exception if the request is
                                unsuccessful (default: True)

        :returns: A Response object from the requests library.
        """
        args: Dict[str, Any] = {"url": config.maas["api_url"] + path}
        args["data"] = json.dumps(data) if data else None
        args["params"] = params if params else None
        args["files"] = files if files else None

        resp: Optional[Response] = None
        method_upper = method.upper()

        if method_upper == "GET":
            resp = self.session.get(**args)
        elif method_upper == "POST":
            resp = self.session.post(**args)
        elif method_upper == "PUT":
            resp = self.session.put(**args)
        elif method_upper == "DELETE":
            resp = self.session.delete(**args)
        else:
            raise RuntimeError(f"Unsupported HTTP method '{method}'")

        if not resp.ok:
            self.log.error("Got status %s from %s: '%s'", resp.status_code, path, resp.text)

        if raise_on_error:
            resp.raise_for_status()

        return resp

    def get_machines_data(self) -> Dict[str, Any]:
        """Locate the machine we want to use

        :returns: The machine data as a dictionary
        """
        resp = self.do_request(
            "/machines/", params={"hostname": self.shortname}
        ).json()
        if len(resp) == 0:
            raise RuntimeError("Machine %s not found!", self.shortname)
        if len(resp) > 1:
            raise RuntimeError(
                "More than one machine found for hostname %s: %s",
                self.shortname, ", ".join([m.get("hostname", "") for m in resp])
            )
        return resp[0]

    def get_image_data(self) -> Dict[str, Any]:
        """Locate the image we want to use

        :returns: The image data as a dictionary
        """
        resp = self.do_request("/boot-resources/").json()
        if len(resp) == 0:
            raise RuntimeError("MaaS has no images available")

        os_version = OS._version_to_codename(self.os_type, self.os_version)
        name = f"{self.os_type}/{os_version}"
        for image in resp:
            if image["name"] == name:
                return image
        raise RuntimeError("MaaS has no %s image", name)

    def lock_machine(self) -> None:
        """Lock the machine"""
        resp = self.do_request(
            f"/machines/{self.system_id}/op-lock", method="POST"
        )

        if resp.text == "Machine is locked":
            log.info("Machine %s is locked", self.shortname)
        elif data := resp.json():
            if not data.get("locked"):
                raise RuntimeError(
                    "Machine %s locking failed, status: %s",
                    self.shortname, data.get("locked")
                )

    def unlock_machine(self) -> None:
        """Unlock the machine"""
        resp = self.do_request(
            f"/machines/{self.system_id}/op-unlock", method="POST"
        )

        if resp.text == "Cannot unlock an already-unlocked node":
            log.info("Machine %s is not locked", self.shortname)
        elif data := resp.json():
            if data.get("locked"):
                raise RuntimeError(
                    "Machine %s locking failed, status %s",
                    self.shortname, data.get("locked")
                )

    def deploy_machine(self) -> None:
        """Deploy the machine"""
        image_data: Dict[str, Any] = self.get_image_data()
        if image_data.get("type", "").lower() not in ["synced", "uploaded"]:
            raise RuntimeError(
                "MaaS image %s is not synced, current status: %s",
                image_data.get("name"), image_data.get("type")
            )

        log.info(
            "Deploying machine %s with image %s", self.shortname, image_data.get("name")
        )
        files = {
            "distro_series": (None, image_data.get("name")),
            "user_data": (None, self._get_user_data()),
        }
        data: Dict[str, Any] = self.do_request(
            f"/machines/{self.system_id}/op-deploy", method="POST", files=files
        ).json()
        if data.get("status_name", "").lower() != "deploying":
            raise RuntimeError(
                "Machine %s deployment failed, status: %s",
                self.shortname, data.get("status_name")
            )

    def release_machine(self, erase: bool = True) -> None:
        """Release the machine

        :param erase: Optional parameter to indicate whether to erase disks
                        (default: True)
        """
        data: Dict[str, bool] = {"erase": erase}
        resp: Dict[str, Any] = self.do_request(
            f"/machines/{self.system_id}/op-release", method="POST", data=data
        ).json()
        if resp.get("status_name", "").lower() not in ["disk erasing", "releasing"]:
            raise RuntimeError(
                "Machine %s releasing failed, status %s",
                self.shortname, resp.get("status_name")
            )

    def abort_deploy(self) -> None:
        """Abort deployment of the machine"""
        machine = self.get_machines_data()
        _status = machine.get("status_name", "").lower()
        if _status != "deploying":
            log.info("Unexpected status %s to abort operation", _status)
            return

        resp: Dict[str, Any] = self.do_request(
            f"/machines/{self.system_id}/op-abort", method="POST"
        ).json()
        if resp.get("status_name", "").lower() != "allocated":
            raise RuntimeError(
                "Failed to abort deploy for machine %s, system_id %s",
                self.shortname, self.system_id
            )

    def create(self) -> None:
        """Create the machine"""
        machine = self.get_machines_data()
        _status = machine.get("status_name", "").lower()
        if _status == "deployed":
            os_type = machine.get("osystem")
            os_version = OS._codename_to_version(
                os_type, machine.get("distro_series")
            )
            log.info(
                "Machine %s is deployed with OS type %s and version %s",
                self.shortname, os_type, os_version
            )
            if (self.os_type, self.os_version) == (os_type, os_version):
                log.info(
                    "Locking machine %s as os requirement are already met",
                    self.shortname
                )
                self.lock_machine()
                return
            log.info("Releasing machine %s for deployment", self.shortname)
            self.release_machine()

        elif _status not in ["ready", "allocated"]:
            raise RuntimeError(
                "MaaS machine %s is not ready or allocated, current status is %s",
                self.shortname, _status
            )

        try:
            log.info(
                "Deploying machine with os type %s and version %s",
                self.os_type, self.os_version
            )
            self.deploy_machine()
            self._wait_for_status("Deployed")
        except Exception as e:
            log.error(
                "Error during deployment of machine %s, aborting deployment\n%s",
                self.shortname, str(e)
            )
            self.abort_deploy()
            self._wait_for_status("Ready")
            return

        self.lock_machine()
        self._verify_installed_os()

    def release(self) -> None:
        """Release the machine"""
        machine_data: Dict[str, Any] = self.get_machines_data()
        if machine_data.get("locked"):
            log.info("Unlocking machine %s before release", self.shortname)
            self.unlock_machine()

        log.info("Releasing machine %s", self.shortname)
        self.release_machine()
        self._wait_for_status("ready")

    def _get_user_data(self) -> Optional[io.BytesIO]:
        """Get user data for cloud-init

        :returns: BytesIO object containing formatted user data, or None if no template
        """
        user_data_template = config.maas.get("user_data")
        if not user_data_template:
            return None

        user_data_template = user_data_template.format(
            os_type=self.os_type, os_version=self.os_version
        )
        return open(user_data_template, "rb")

    def _wait_for_status(
            self, status: str, interval: int = 60, timeout: int = 900
        ) -> None:
        """Wait for the machine to reach a specific status

        :param status: The status to wait for
        :param interval: Time to wait between status checks, in seconds (default: 60)
        :param timeout: Maximum time to wait for the status, in seconds (default: 900)
        """
        log.info(
            "Waiting for machine %s with system_id %s to reach status %s",
            self.shortname, self.system_id, status
        )
        with safe_while(
            sleep=interval, timeout=int(config.maas.get("timeout", timeout))
        ) as proceed:
            while proceed():
                maas_machine: Dict[str, Any] = self.get_machines_data()
                status_name = maas_machine["status_name"]
                if status_name.lower() == status.lower():
                    log.info(
                        "MaaS machine system %s with system_id %s reached status %s",
                        self.shortname, self.system_id, status_name
                    )
                    return

                log.debug(
                    "MaaS machine system %s with system_id %s is still in status %s",
                    self.shortname, self.system_id, status_name
                )

        raise RuntimeError(
            "Failed to validate status %s for machine %s with system_id %s",
            status, self.shortname, self.system_id
        )

    def _verify_installed_os(self) -> None:
        """Verify that the installed OS matches the expected OS"""
        wanted_os = OS(name=self.os_type, version=self.os_version)
        if self.remote.os != wanted_os:
            raise RuntimeError(
                "Expected %s's OS to be %s but found %s",
                self.remote.shortname, wanted_os, self.remote.os
            )
