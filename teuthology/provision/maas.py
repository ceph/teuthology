import io
import json
import logging
import operator

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

        self.os_type, self.os_version, self.arch, self.system_id = self._get_system_info()
        if (self.os_type, self.os_version, os_type, os_version).count(None) == 4:
            raise RuntimeError(f"Unable to find OS details for machine {name}")

        if ((os_type and os_version) and
                (self.os_type, self.os_version) != (os_type, os_version)):
            self.log.warning(
                f"User provided '{os_type}', '{os_version}' and machine "
                f"'{self.os_type}', '{self.os_version}' os details are not matching"
            )
            self.os_type, self.os_version = os_type, os_version

    def _get_system_info(self) -> Tuple[Optional[str], Optional[str], str, str]:
        """Get the system info for the deployed machine

        :returns: A tuple (os_type, os_version, system_id)
                    For machines in 'Ready' state, os_type and os_version will be None
        """
        machine = self.get_machines_data()
        status_name = machine.get("status_name", "").lower()
        arch = machine.get("architecture")
        if status_name == "ready":
            return None, None, arch, machine.get("system_id")

        if status_name in ["deployed", "allocated"]:
            os_type = machine.get("osystem", "").lower()
            os_version = OS._codename_to_version(
                os_type, machine.get("distro_series")
            )
            return os_type, os_version, arch, machine.get("system_id")

        raise RuntimeError(
            f"MaaS machine '{self.shortname}' is not 'Ready' or 'Deployed', "
            f"current status is '{status_name}'"
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
            self.log.error(f"Got status {resp.status_code} from {path}: '{resp.text}'")

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
            raise RuntimeError(f"Machine '{self.shortname}' not found!")
        if len(resp) > 1:
            hostnames = ", ".join([m.get("hostname", "") for m in resp])
            raise RuntimeError(
                f"More than one machine found for hostname '{self.shortname}': {hostnames}"
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
            major_image_arch = image["architecture"].split('/')[0]
            major_machine_arch = self.arch.split('/')[0]
            if image["name"] == name and major_image_arch == major_machine_arch:
                return image
        raise RuntimeError(f"MaaS has no {name} image for {major_machine_arch}. Available images: {self.suggest_image_names()}")

    def suggest_image_names(self):
        """
        Suggest available image names.

        :returns: A list of image names.
        """
        resp = self.do_request('/boot-resources/')
        images = resp.json()
        return '\n'.join([' '.join((image['name'], image['architecture'])) for image in images])

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
            self.log.info(f"Machine '{self.shortname}' is not locked")
        elif data := resp.json():
            if data.get("locked"):
                raise RuntimeError(
                    f"Machine '{self.shortname}' unlocking failed, "
                    f"Current status: {data.get('locked')}"
                )
        self.release_machine(erase=False)
        self._wait_for_status(status="Deployed", is_not=True)

    def deploy_machine(self) -> None:
        """Deploy the machine"""
        image_data: Dict[str, Any] = self.get_image_data()
        if image_data.get("type", "").lower() not in ["synced", "uploaded"]:
            raise RuntimeError(
                f"MaaS image {image_data.get('name')} is not synced, "
                f"current status: {image_data.get('type')}"
            )

        self.log.info(
            f"Deploying machine '{self.shortname}' with image {image_data.get('name')}"
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
                f"Machine '{self.shortname}' releasing failed, "
                f"current status is {resp.get('status_name')}",
            )

    def abort_deploy(self) -> None:
        """Abort deployment of the machine"""
        machine = self.get_machines_data()
        status_name = machine.get("status_name", "").lower()
        if status_name != "deploying":
            self.log.info(
                f"Cannot abort machine in '{status_name}' state;"
                "skipping abort operation.")
            return

        resp: Dict[str, Any] = self.do_request(
            f"/machines/{self.system_id}/op-abort", method="POST"
        ).json()
        if resp.get("status_name", "").lower() != "allocated":
            raise RuntimeError(
                f"Failed to abort deploy for machine '{self.shortname}' "
                f"with system_id '{self.system_id}'"
            )

    def create(self) -> None:
        """Create the machine"""
        machine = self.get_machines_data()
        status_name = machine.get("status_name", "").lower()
        if status_name == "deployed":
            os_type = machine.get("osystem")
            os_version = OS._codename_to_version(
                os_type, machine.get("distro_series")
            )

            self.log.info(
                f"Machine '{self.shortname}' is deployed with OS type "
                f"'{os_type}' and version '{os_version}'"
            )

            self.log.info(f"Releasing machine '{self.shortname}' for deployment")
            self.release_machine()

        elif status_name not in ["ready", "allocated"]:
            raise RuntimeError(
                f"MaaS machine '{self.shortname}' is not ready or allocated, "
                f"current status is '{status_name}'"
            )

        try:
            self.log.info(
                f"Deploying machine with os type '{self.os_type}' "
                f"and version '{self.os_version}'"
            )
            self.deploy_machine()
            self._wait_for_status("Deployed")
        except Exception as e:
            self.log.error(
                f"Error during deployment of machine '{self.shortname}',"
                f"aborting deployment\n'{str(e)}'"
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
            self.log.info(f"Unlocking machine '{self.shortname}' before release")
            self.unlock_machine()

        self.log.info(f"Releasing machine '{self.shortname}'")
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
            self, status: str, is_not: bool = False, interval: int = 60, timeout: int = 900
        ) -> None:
        """Wait for the machine to reach a specific status, or to no longer
        have a specific status

        :param status: The status to wait for
        :param is_not: If True, wait for reported status *not* matching status
        :param interval: Time to wait between status checks, in seconds (default: 60)
        :param timeout: Maximum time to wait for the status, in seconds (default: 900)
        """
        if is_not:
            compare = operator.ne
            success = "leave"
            succeeded = "left"
        else:
            compare = operator.eq
            success = "reach"
            succeeded = "reached"

        self.log.info(
            f"Waiting for machine '{self.shortname}' with system_id '{self.system_id}' "
            f"to {success} status '{status}'"
        )
        with safe_while(
            sleep=interval, timeout=int(config.maas.get("timeout", timeout))
        ) as proceed:
            while proceed():
                maas_machine: Dict[str, Any] = self.get_machines_data()
                status_name = maas_machine["status_name"]

                if compare(status_name.lower(), status.lower()):
                    log.info(
                        f"MaaS machine system '{self.shortname}' with system_id "
                        f"'{self.system_id}' {succeeded} status '{status_name}'"
                    )
                    if is_not:
                        log.info(f"New status: '{status_name}'")
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
