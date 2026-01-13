import io
import json
import logging

from oauthlib.oauth1 import SIGNATURE_PLAINTEXT
from requests import Response
from requests_oauthlib import OAuth1Session
from typing import Any, Dict, List, Optional, Union

import teuthology.orchestra

from teuthology.config import config
from teuthology.contextutil import safe_while
from teuthology.orchestra.opsys import OS
from teuthology import misc
from requests.exceptions import HTTPError

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
        unset = " ".join(unset)
        log.warning(
            f"MAAS disabled; set the following config options to enable: {unset}",
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
            self, name: str, os_type: str = "ubuntu", os_version: str = "22.04"
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
        self.os_type = os_type
        self.os_version = os_version

        self.log = log.getChild(self.shortname)

        _info = self.get_machines_data()
        self.system_id = _info.get("system_id")
        self.cpu_arch, arch_variant = _info.get("architecture").split("/")

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
        args: Dict[str, Any] = {"url": f"{config.maas['api_url'].strip('/')}/{path}"}
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
            self.log.error(f"Got status {resp.status_code} from {path}: '{resp.text}'")

        if raise_on_error:
            resp.raise_for_status()

        return resp

    def get_machines_data(self, interval: int = 3, timeout: int = 30) -> Dict[str, Any]:
        """Locate the machine we want to use

        :param interval: Time to wait between retries, in seconds (default: 3)
        :param timeout: Maximum time to wait for the machine, in seconds (default: 30)

        :returns: The machine data as a dictionary
        """
        resp = []
        with safe_while(
            sleep=interval, timeout=int(config.maas.get("timeout", timeout))
        ) as proceed:
            while proceed():
                try:
                    resp = self.do_request(
                        "/machines/", params={"hostname": self.shortname}
                    ).json()
                    break
                except HTTPError as e:
                    log.error(
                        f"Error locating machine '{self.shortname}': {str(e)}\n",
                        f"retrying after {interval} ..."
                    )

        if len(resp) == 0:
            raise RuntimeError(f"Machine '{self.shortname}' not found!")
        if len(resp) > 1:
            hostnames = ", ".join([m.get("hostname", "") for m in resp])
            raise RuntimeError(
                f"More than one machine found for hostname '{self.shortname}': {hostnames}"
            )
        return resp[0]

    def get_image_name(self) -> str:
        match self.os_type:
            case 'ubuntu':
                os_version = OS._version_to_codename(self.os_type, self.os_version)
                return f"{self.os_type}/{os_version}"
            case 'centos':
                os_version = self.os_version.replace('.', '-')
                return f"{self.os_type}/{self.os_type}{os_version}"
        return f"{self.os_type}/{self.os_version}"

    def get_image_data(self) -> Dict[str, Any]:
        """Locate the image we want to use

        :returns: The image data as a dictionary
        """
        resp = self.do_request("/boot-resources/").json()
        if len(resp) == 0:
            raise RuntimeError("MaaS has no images available")

        name = self.get_image_name()
        for image in resp:
            if image["name"] == name and self.cpu_arch in image["architecture"]:
                return image
        raise RuntimeError(f"MaaS has no {name} image available")

    def lock_machine(self) -> None:
        """Lock the machine"""
        resp = self.do_request(
            f"/machines/{self.system_id}/op-lock", method="POST"
        )

        if resp.text == "Machine is locked":
            self.log.info(f"Machine '{self.shortname}' is locked")
        elif data := resp.json():
            if not data.get("locked"):
                raise RuntimeError(
                    f"Machine '{self.shortname}' locking failed, "
                    f"Current status: {data.get('locked')}"
                )

    def unlock_machine(self) -> None:
        """Unlock the machine"""
        resp = self.do_request(
            f"/machines/{self.system_id}/op-unlock", method="POST"
        )
        if resp.text == "Cannot unlock an already-unlocked node":
            self.log.info(
                f"Machine '{self.shortname}' is not locked; skipping unlock ..."
            )

        elif data := resp.json():
            if data.get("locked"):
                raise RuntimeError(
                    f"Machine '{self.shortname}' unlocking failed, "
                    f"Current status: {data.get('locked')}"
                )

    def deploy_machine(self) -> None:
        """Deploy the machine"""
        image_data: Dict[str, Any] = self.get_image_data()
        if image_data.get("type", "").lower() not in ["synced", "uploaded"]:
            raise RuntimeError(
                f"MaaS image {image_data.get('name')} is not synced, "
                f"current status: {image_data.get('type')}"
            )

        self.log.info(
            f"Deploying machine '{self.shortname}', arch '{self.cpu_arch}' "
            f"with image {image_data.get('name')}"
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
                f"Machine '{self.shortname}' deployment failed, "
                f"Current status: {data.get('status_name')}",
            )

    def release_machine(self, erase: bool = False) -> None:
        """Release the machine

        :param erase: Optional parameter to indicate whether to erase disks
                        (default: False)
        """
        data: Dict[str, bool] = {"erase": erase}
        resp: Dict[str, Any] = self.do_request(
            f"/machines/{self.system_id}/op-release", method="POST", data=data
        ).json()
        if resp.get("status_name", "").lower() not in ["disk erasing", "releasing", "ready"]:
            raise RuntimeError(
                f"Machine '{self.shortname}' releasing failed, "
                f"current status is {resp.get('status_name')}",
            )
        self._wait_for_status("ready")

    def abort_deploy(self) -> None:
        """Abort deployment of the machine"""
        machine = self.get_machines_data()
        status_name = machine.get("status_name", "").lower()
        if status_name != "deploying":
            self.log.info(
                f"Cannot abort machine in '{status_name}' state; "
                "skipping abort operation.")
            return

        self.do_request(f"/machines/{self.system_id}/op-abort", method="POST")
        self.log.info(
            f"Aborted deployment of machine '{self.shortname}', "
            "waiting for 'Allocated' status")
        self._wait_for_status("allocated")

    def create(self) -> None:
        """Create the machine"""
        machine = self.get_machines_data()
        status_name = machine.get("status_name", "").lower()
        if status_name == "deployed":
            self.log.info(f"Machine '{self.shortname}' is already deployed; releasing")
            self.release_machine()

        elif status_name not in ["ready", "allocated"]:
            raise RuntimeError(
                f"MaaS machine '{self.shortname}' is not ready or allocated, "
                f"current status is '{status_name}'"
            )

        try:
            self.log.info(
                f"Deploying machine with os type '{self.os_type}' "
                f"arch {self.cpu_arch} and version '{self.os_version}'"
            )
            self.deploy_machine()
            self._wait_for_status("Deployed")
        except Exception as e:
            self.log.error(
                f"Error during deployment of machine '{self.shortname}', "
                f"aborting deployment\n'{str(e)}'"
            )
            self.abort_deploy()
            self._wait_for_status("Ready")
            raise RuntimeError(
                f"Deployment of machine '{self.shortname}' failed"
            ) from e

        self.lock_machine()
        self._verify_installed_os()

    def release(self) -> None:
        """Release the machine"""
        machine_data: Dict[str, Any] = self.get_machines_data()
        status_name = machine_data.get("status_name", "").lower()

        if status_name in ["new", "allocated", "ready"]:
            self.log.info(f"Machine '{self.shortname}' is already released")
            return

        elif status_name == "deploying":
            self.log.info(
                f"Machine '{self.shortname}' is deploying; aborting deployment before release"
            )
            self.abort_deploy()

        elif status_name == "deployed":
            if machine_data.get("locked"):
                self.log.info(f"Unlocking machine '{self.shortname}' before release")
                self.unlock_machine()

        else:
            raise RuntimeError(
                f"Cannot release machine '{self.shortname}' in status '{status_name}'"
            )

        self.log.info(f"Releasing machine '{self.shortname}'")
        self.release_machine()

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
        self.log.info(
            f"Waiting for machine '{self.shortname}' with system_id '{self.system_id}' "
            f"to reach status '{status}'"
        )
        with safe_while(
            sleep=interval, timeout=int(config.maas.get("timeout", timeout))
        ) as proceed:
            while proceed():
                maas_machine: Dict[str, Any] = self.get_machines_data()
                status_name = maas_machine["status_name"]
                if status_name.lower() == status.lower():
                    log.info(
                        f"MaaS machine system '{self.shortname}' with system_id "
                        f"'{self.system_id}' reached status '{status_name}'"
                    )
                    return

                self.log.debug(
                    f"MaaS machine system '{self.shortname}' with system_id "
                    f"'{self.system_id}' is still in status '{status_name}'"
                )

        raise RuntimeError(
            f"Failed to validate status '{status}' for machine '{self.shortname}' "
            f"with system_id '{self.system_id}'"
        )

    def _verify_installed_os(self) -> None:
        """Verify that the installed OS matches the expected OS"""
        wanted_os = OS(name=self.os_type, version=self.os_version)
        if self.remote.os != wanted_os:
            raise RuntimeError(
                f"Expected {self.remote.shortname}'s OS to be '{wanted_os}' "
                f"but found '{self.remote.os}'"
            )
