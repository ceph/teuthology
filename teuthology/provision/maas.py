import json
import logging

from oauthlib.oauth1 import SIGNATURE_PLAINTEXT
from requests_oauthlib import OAuth1Session

import teuthology.orchestra

from teuthology.config import config
from teuthology.contextutil import safe_while
from teuthology.orchestra.opsys import OS
from teuthology import misc

log = logging.getLogger(__name__)

ubuntu_codenames = {
    "20.04": "focal",
    "22.04": "jammy",
    "24.04": "noble",
    "25.04": "plucky",
    "25.10": "questing",
}

def enabled(warn=False):
    """Check for required MaaS settings

    :param warn: Whether or not to log a message containing unset parameters
    :returns: True if they are present; False if they are not
    """
    maas_conf = config.get("maas", dict())
    params = ["api_url", "api_key", "machine_types"]
    unset = [param for param in params if not maas_conf.get(param)]
    if unset and warn:
        log.warning(
            "MaaS disabled; set the following config options to enable: %s",
            " ".join(unset),
        )

    if unset:
        if not config.get("maas", dict()).get("api_url"):
            return False

        api_key = config.get("maas", dict()).get("api_key", None)
        if not api_key:
            return False
        if len(api_key.split(":")) < 3:
            log.warning(
                "MaaS api_key appears to be malformed; expected format is "
                "'consumer_key:consumer_token:secret'"
            )
            return False

    return True


def get_types():
    """Fetch and parse maas machine_types config

    :returns: The list of MaaS-configured machine types. 
              An empty list if MAAS is not configured.
    """
    if not enabled():
        return []
    maas_conf = config.get("maas", dict())
    types = maas_conf.get("machine_types", "")
    if not isinstance(types, list):
        types = types.split(",")
    return [type_ for type_ in types if type_]


def get_session():
    """Create an OAuth1Session for communicating with the MaaS server"""
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

    def __init__(self, name,  os_type=None, os_version=None):
        """Initialize the MAAS object

        :param name: The fully-qualified domain name of the machine to manage
        :param os_type: The OS type to deploy (e.g. "ubuntu")
        :param os_version: The OS version to deploy (e.g. "22.04")
        """
        self.session = get_session()

        self.remote = teuthology.orchestra.remote.Remote(
            misc.canonicalize_hostname(name))
        self.name = self.remote.hostname
        self.shortname = self.remote.shortname

        self.log = log.getChild(self.shortname)

        self.os_type, self.os_version, self.system_id = self._get_system_info(
            os_type, os_version)

    def _get_system_info(self, os_type, os_version):
        """Get the system info string for the deployed OS

        :param os_type: The OS type as a string
        :param os_version: The OS version as a string
        :returns: os type, version, and system id as strings
        """
        _os_type, _os_version = None, None

        maas_machine = self.get_machines_data()
        if maas_machine.get("status_name").lower() == "ready":
            if not (os_type and os_version):
                raise RuntimeError(
                    "Machine %s is not deployed, please provide "
                    "OS type and version" % self.shortname)
            _os_type, _os_version = os_type.lower(), str(os_version)
        elif maas_machine.get("status_name").lower() == "deployed":
            if os_type and os_version:
                _os_type, _os_version = os_type.lower(), str(os_version)
            else:
                _os_type = maas_machine.get("osystem", "").lower()
                _os_version = self._get_os_version(
                    maas_machine.get("distro_series", "").lower()
                )
        else:
            raise RuntimeError(
                "MaaS machine %s is not ready or deployed, current status: %s"
                % (self.shortname, maas_machine.get("status_name"))
            )

        return _os_type, _os_version, maas_machine.get("system_id")

    def _get_os_version(self, os_codename):
        """Get the OS version of the deployed OS

        :param os_codename: The OS codename as a string
        :returns: The OS version as a string
        """
        for version in ubuntu_codenames.keys():
            if ubuntu_codenames[version] == os_codename:
                return version

    def do_request(
            self,
            path,
            method="GET",
            params=None,
            data=None,
            files=None,
            raise_on_error=True
    ):
        """A convenience method to submit a request to the
        MAAS server

        :param path: The path of the URL to append to the endpoint,
                           e.g.  "/machines/"
        :param method: The HTTP method to use for the request
                        (default: "GET")
        :param params: Optional query/operation parameters to 
                        submit with the request
        :param data: Optional JSON data to submit with the request
        :param files: Optional file data to submit with the request
        :param raise_on_error: Whether or not to raise an exception
                               if the request is unsuccessful 
                               (default: True)
        
        :returns: A requests output
        """
        args = {"url": config.maas["api_url"] + path}
        args["data"] = json.dumps(data) if data else None
        args["params"] = params if params else None
        args["files"] = files if files else None

        resp = None
        if method == "GET":
            resp = self.session.get(**args)
        elif method == "POST":
            resp = self.session.post(**args)
        elif method == "PUT":
            resp = self.session.put(**args)
        elif method == "DELETE":
            resp = self.session.delete(**args)
        else:
            raise RuntimeError("Unsupported HTTP method '%s'", method)

        if not resp.ok:
            self.log.error(
                "Got status %s from %s: '%s'",
                resp.status_code, path, resp.text
            )

        if raise_on_error:
            resp.raise_for_status()

        return resp

    def get_machines_data(self):
        """Locate the machine we want to use

        returns: The machine data as a dict
        """
        resp = self.do_request(
            "/machines/", params={"hostname": self.shortname}
        ).json()
        if len(resp) == 0:
            raise RuntimeError("Machine %s not found!" % self.shortname)
        if len(resp) > 1:
            raise RuntimeError(
                "More than one machine found for %s" % self.shortname
            )
        return resp[0]

    def get_image_data(self):
        """Locate the image we want to use

        :returns: The image data as a dict
        """
        resp = self.do_request("/boot-resources/").json()
        if len(resp) == 0:
            raise RuntimeError("MaaS has no images available.")

        name = "%s/%s" % (
            self.os_type,
            ubuntu_codenames.get(self.os_version)
            if self.os_type == "ubuntu" else self.os_version
        )
        for image in resp:
            if image["name"] == name:
                return image
        raise RuntimeError("MaaS has no %s image." % name)

    def lock_machine(self, raise_on_error=True):
        """Lock the machine

        :param raise_on_error: Whether or not to raise an exception
                               if the request is unsuccessful (default: True)
        """
        resp = self.do_request(
            f"/machines/{self.system_id}/op-lock",
            method="POST",
            raise_on_error=raise_on_error
        )
        if resp.json():
            if not resp.json().get("locked") and raise_on_error:
                raise RuntimeError(
                    "Machine %s locking failed, status: %s",
                    self.shortname, resp.json().get("locked")
                )
        elif raise_on_error:
            raise RuntimeError(
                "Failed to lock machine %s, system_id: %s",
                self.shortname, self.system_id
            )

    def unlock_machine(self, raise_on_error=True):
        """Unlock the machine

        :param raise_on_error: Whether or not to raise an exception
                               if the request is unsuccessful (default: True)
        """
        resp = self.do_request(
            f"/machines/{self.system_id}/op-unlock",
            method="POST",
            raise_on_error=raise_on_error
        )
        if resp.json():
            if resp.json().get("locked") and raise_on_error:
                raise RuntimeError(
                    "Machine %s locking failed, status: %s",
                    self.shortname, resp.json().get("locked")
                )
        elif raise_on_error:
            raise RuntimeError(
                "Failed to lock machine %s, system_id: %s",
                self.shortname, self.system_id
            )

    def deploy_machine(self):
        """Deploy the machine"""
        image_data = self.get_image_data()
        if image_data.get("type").lower() != "synced":
            raise RuntimeError(
                "MaaS image %s is not synced, current status: %s",
                image_data.get("name"), image_data.get("type")
            )
        log.info(
            "Deploying machine %s with image %s",
            self.shortname, image_data.get("name")
        )
    
        files = {
            "distro_series": (None, image_data.get("name")),
            "user_data": (None, self._get_user_data()),
        }
        resp = self.do_request(
            f"/machines/{self.system_id}/op-deploy", method="POST", files=files
        ).json()
        if not resp:
            raise RuntimeError(
                "Failed to deploy machine %s, system_id: %s",
                self.shortname, self.system_id
            )
        if not resp.get("status_name").lower() == "deploying":
            raise RuntimeError(
                "Machine %s deployment failed, status: %s",
                self.shortname, resp.get("status_name")
            )

    def release_machine(self, erase=True):
        """Release the machine

        params: Optional parameters for the erasing disks
        """
        data = { "erase": erase }
        resp = self.do_request(
            f"/machines/{self.system_id}/op-release", method="POST", data=data
        ).json()
        if not resp:
            raise RuntimeError(
                "Failed to release machine %s, system_id: %s",
                self.shortname, self.system_id
            )
        if not resp.get("status_name").lower() == "disk erasing":
            raise RuntimeError(
                "Machine %s releasing failed, status: %s",
                self.shortname, resp.get("status_name")
            )

    def abort_deploy(self):
        """Abort deployment of the machine"""
        resp = self.do_request(
            f"/machines/{self.system_id}/op-abort", method="POST"
        ).json()
        if not resp:
            raise RuntimeError(
                "Failed to abort deploy for machine %s, system_id: %s",
                self.shortname, self.system_id
            )

    def create(self):
        """Create the machine"""
        machine_status = self.get_machines_data().get("status_name").lower()
        if machine_status == "deployed":
            log.info("Machine %s is already deployed", self.shortname)
            self.lock_machine(raise_on_error=False)
            try:
                self._verify_installed_os()
                return
            except RuntimeError:
                self.release()
        elif machine_status != "ready":
            raise RuntimeError(
                "MaaS machine %s is not ready, current status: %s",
                self.shortname, machine_status
            )

        try:
            self.deploy_machine()
            self._wait_for_status("Deployed")
        except Exception:
            log.error(
                "Error during deployment of machine %s, aborting deployment",
                self.shortname
            )
            self.abort_deploy()
            self._wait_for_status("Ready")
            raise RuntimeError(
                "MaaS machine %s is not ready, current status: %s",
                self.shortname, machine_status
            )

        self.lock_machine()
        self._verify_installed_os()

    def release(self):
        """Release the machine"""
        machine_data = self.get_machines_data()
        if machine_data.get("locked"):
            log.info("Unlocking machine %s before release", self.shortname)
            self.unlock_machine()

        log.info("Releasing machine %s", self.shortname)
        self.release_machine()
        self._wait_for_status("Ready")

    def _get_user_data(self):
        """Get user data for cloud-init"""
        user_data_template = config.maas.get("user_data")
        if not user_data_template:
            return None

        user_data_template = user_data_template.format(
            os_type=self.os_type, os_version=self.os_version)
        return open(user_data_template, "rb")

    def _wait_for_status(self, status):
        """Wait for the machine to reach a specific status

        :param status: The status to wait for
        """
        log.info(
            "Waiting for machine %s to reach status: %s",
            self.shortname, status
        )
        with safe_while(
            sleep=10, timeout=int(config.maas.get("timeout", 900))
        ) as proceed:
            while proceed():
                maas_machine = self.get_machines_data()
                status_name = maas_machine["status_name"]
                if status_name.lower() == status.lower():
                    log.info(
                        "MaaS machine system Id: %s reached status: %s",
                        self.system_id, status_name
                    )
                    return

                log.info(
                    "MaaS machine system Id: %s is still in status: %s",
                    self.system_id, status_name
                )

        raise RuntimeError(
            "Failed to validate status %s for machine %s, system_id: %s",
            status, self.shortname, self.system_id
        )

    def _verify_installed_os(self):
        """Verify that the installed OS matches the expected OS"""
        wanted_os = OS(name=self.os_type, version=self.os_version)
        if self.remote.os != wanted_os:
            raise RuntimeError(
                f"Expected {self.remote.shortname}'s OS to be {wanted_os} but "
                f"found {self.remote.os}"
            )
