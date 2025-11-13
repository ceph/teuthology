import base64
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


def enabled(warn=False):
    """Check for required MaaS settings

    :param warn: Whether or not to log a message containing unset parameters

    :returns: True if they are present; False if they are not
    """
    maas_conf = config.get("maas", dict())
    params = ["endpoint", "api_key", "machine_types"]
    unset = [param for param in params if not maas_conf.get(param)]
    if unset and warn:
        log.warning(
            "MaaS disabled; set the following config options to enable: %s",
            " ".join(unset),
        )

    if unset:
        api_key = config.get("maas", dict()).get("api_key", None)
        if api_key and api_key.split(":") < 3:
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


def release_machine(name):
    """Release a machine from MAAS management

    :param name: The fully-qualified domain name of the machine to release
    """
    MAAS(name, os_type="", os_version="").release()


class MAAS(object):
    """Reimage machines with https://maas.io"""

    def __init__(self, name,  os_type, os_version):
        """Initialize the MAAS object

        :param name: The fully-qualified domain name of the machine to manage
        :param os_type: The OS type to deploy (e.g. "ubuntu")
        :param os_version: The OS version to deploy (e.g. "noble")
        """
        if not enabled():
            raise RuntimeError("MAAS is not configured!")

        self.remote = teuthology.orchestra.remote.Remote(
            misc.canonicalize_hostname(name))
        self.name = self.remote.hostname
        self.shortname = self.remote.shortname
        self.os_type = os_type
        self.os_version = os_version

        self.log = log.getChild(self.shortname)

        self.session = self._session()
        self.system_id = self.get_host_data()["system_id"]

    def _session(self):
        """Create an OAuth1Session for communicating with the MaaS server"""
        key, token, secret = config.maas["api_key"].split(":")
        return OAuth1Session(
            key,
            resource_owner_key=token,
            resource_owner_secret=secret,
            signature_method=SIGNATURE_PLAINTEXT
        )

    def do_request(
            self, url_suffix, method="GET", params=None, data=None, verify=True
    ):
        """A convenience method to submit a request to the MAAS server

        :param url_suffix: The portion of the URL to append to the endpoint,
                           e.g.  "/machines/"
        :param method: The HTTP method to use for the request (default: "GET")
        :param params: Optional query/operation parameters to submit with
                       the request
        :param data: Optional JSON data to submit with the request
        :param verify: Whether or not to raise an exception if the request is
                       unsuccessful (default: True)
        
        :returns: A requests output
        """
        args = {"url": config.maas["endpoint"] + url_suffix}
        args["data"] = json.dumps(data) if data else None
        args["params"] = params if params else None
        args["headers"] = (
            {"Content-Type": "application/json"} if params or data else None
        )

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
                resp.status_code, url_suffix, resp.text
            )

        if verify:
            resp.raise_for_status()

        return resp

    def get_host_data(self):
        """Locate the host we want to use

        returns: The host data as a dict
        """
        resp = self.do_request(
            "/machines/", params={"hostname": self.shortname}
        ).json()
        if len(resp) == 0:
            raise RuntimeError("Host %s not found!" % self.shortname)
        if len(resp) > 1:
            raise RuntimeError(
                "More than one host found for %s" % self.shortname
            )
        return resp[0]

    def get_image_data(self):
        """Locate the image we want to use

        :returns: The image data as a dict
        """
        resp = self.do_request("/boot-resources/").json()
        if len(resp) == 0:
            raise RuntimeError("MaaS has no images available.")

        """
        TODO: `do-deploy` is not honoring `distro_series` hence setting image
        name to default 'noble'. Refer Bug -
        https://bugs.launchpad.net/maas/+bug/1923315
        """
        name = f"{self.os_type.lower()}/noble"
        for image in resp:
            if image["name"] == name:
                return image
        raise RuntimeError("MaaS has no %s image." % name)

    def lock_host(self):
        """Lock the machine"""
        resp = self.do_request(
            f"/machines/{self.system_id}/op-lock", method="POST"
        ).json()
        if not resp:
            raise RuntimeError(
                "Failed to lock host %s, system_id: %s",
                self.shortname, self.system_id
            )
        if not resp.get("locked"):
            raise RuntimeError(
                "Host %s locking failed, status: %s",
                self.shortname, resp.get("locked")
            )

    def unlock_host(self):
        """Unlock the machine"""
        resp = self.do_request(
            f"/machines/{self.system_id}/op-unlock", method="POST"
        ).json()
        if not resp:
            raise RuntimeError(
                "Failed to unlock host %s, system_id: %s",
                self.shortname, self.system_id
            )
        if resp.get("locked"):
            raise RuntimeError(
                "Host %s unlocking failed, status: %s",
                self.shortname, resp.get("locked")
            )

    def deploy_host(self):
        """Deploy the machine"""
        image_data = self.get_image_data()
        if image_data.get("type").lower() != "synced":
            raise RuntimeError(
                "MaaS image %s is not synced, current status: %s",
                image_data.get("name"), image_data.get("type")
            )
        data = {
            "distro_series": image_data.get("name"),
            "user_data": self._get_user_data(),
        }

        log.info(
            "Deploying host %s with image %s and data %s",
            self.shortname, image_data.get("name"), data
        )
        resp = self.do_request(
            f"/machines/{self.system_id}/op-deploy", method="POST", data=data
        ).json()
        if not resp:
            raise RuntimeError(
                "Failed to deploy host %s, system_id: %s",
                self.shortname, self.system_id
            )
        if not resp.get("status_name") == "Deploying":
            raise RuntimeError(
                "Host %s deployment failed, status: %s",
                self.shortname, resp.get("status_name")
            )

    def release_host(self, erase=True):
        """Release the machine

        params: Optional parameters for the erasing disks
        """
        data = { "erase": erase }
        resp = self.do_request(
            f"/machines/{self.system_id}/op-release", method="POST", data=data
        ).json()
        if not resp:
            raise RuntimeError(
                "Failed to release host %s, system_id: %s",
                self.shortname, self.system_id
            )
        if not resp.get("status_name").lower() == "disk erasing":
            raise RuntimeError(
                "Host %s releasing failed, status: %s",
                self.shortname, resp.get("status_name")
            )

    def abort_deploy(self):
        """Abort deployment of the machine"""
        resp = self.do_request(
            f"/machines/{self.system_id}/op-abort", method="POST"
        ).json()
        if not resp:
            raise RuntimeError(
                "Failed to abort deploy for host %s, system_id: %s",
                self.shortname, self.system_id
            )

    def create(self):
        """Create the machine"""
        host_data = self.get_host_data()
        if host_data.get("status_name").lower() != "ready":
            raise RuntimeError(
                "MaaS host %s is not ready, current status: %s",
                self.shortname, host_data.get("status_name")
            )

        try:
            self.deploy_host()
            self._wait_for_status("Deployed")
        except Exception:
            log.error(
                "Error during deployment of host %s", self.shortname
            )
            self.abort_deploy()
            self._wait_for_status("Ready")
            raise

        self.lock_host()
        self._verify_installed_os()

    def release(self):
        """Release the machine"""
        host_data = self.get_host_data()
        if host_data.get("locked"):
            log.info("Unlocking host %s before release", self.shortname)
            self.unlock_host()

        log.info("Releasing host %s", self.shortname)
        self.release_host()
        self._wait_for_status("Ready")

    def _get_user_data(self):
        """Get user data for cloud-init"""
        user_data_template = config.maas.get("user-data")
        if not user_data_template:
            return None

        user_data_template = user_data_template.format(
            os_type=self.os_type, os_version=self.os_version)
        with open(user_data_template, "r") as f:
            return base64.b64encode(f.read().encode("utf-8")).decode("utf-8")

    def _wait_for_status(self, status):
        """Wait for the machine to reach a specific status

        :param status: The status to wait for
        """
        log.info(
            "Waiting for host %s to reach status: %s",
            self.shortname, status
        )
        with safe_while(
            sleep=10, timeout=int(config.maas.get("timeout", 900))
        ) as proceed:
            while proceed():
                maas_host = self.get_host_data()
                status_name = maas_host["status_name"]
                if status_name.lower() == status.lower():
                    log.info(
                        "MaaS host system Id: %s reached status: %s", 
                        self.system_id, status_name
                    )
                    return

                log.info(
                    "MaaS host system Id: %s is still in status: %s",
                    self.system_id, status_name
                )

        raise RuntimeError(
            "Failed to validate status %s for host %s, system_id: %s",
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
