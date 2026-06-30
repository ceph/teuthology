import logging

from kubernetes import client, config as kubernetes_config
from typing import List, Optional, Tuple, Dict, Any

from teuthology.orchestra.remote import Remote
from teuthology.config import config
from teuthology.contextutil import safe_while
from teuthology import misc

log = logging.getLogger(__name__)


def enabled(warn: bool = False) -> bool:
    """Check if OpenShift is enabled
    
    :param warn: Whether to log a message containing unset parameters

    :returns: True if all required settings are present; False otherwise
    """
    openshift_conf = config.get("openshift", {})
    params: List[str] = ["namespace", "machine_types"]
    unset = [param for param in params if not openshift_conf.get(param)]
    if unset and warn:
        unset = " ".join(unset)
        log.warning(
            f"OpenShift disabled; set the following config options to "
            f"enable: {unset}",
        )

    if unset:
        if not openshift_conf.get("namespace"):
            return False

        if not openshift_conf.get("machine_types"):
            return False

    return True


def get_types() -> List[str]:
    """Fetch and parse OpenShift machine_types config.

    :returns: The list of OpenShift-configured machine types.
                Returns an empty list if OpenShift is not configured
    """
    if not enabled():
        return []
    types = config.get("openshift", {}).get("machine_types", "")
    if not isinstance(types, list):  # type: ignore
        types = types.split(",")

    return [type_ for type_ in types if type_]


def get_namespace() -> str:
    """Fetch and parse OpenShift namespace config.

    :returns: The OpenShift namespace.
    """
    if not enabled():
        return ""
    return config.get("openshift", {}).get("namespace", "")


def get_session() -> Tuple[client.CustomObjectsApi, client.CoreV1Api]:
    """Get a session for communicating with the OpenShift API"""
    if not enabled():
        raise RuntimeError("OpenShift is not configured!")

    kubernetes_config.load_kube_config()
    return client.CustomObjectsApi(), client.CoreV1Api()


def get_vm_manifest(
    namespace: str,
    vm_name: str,
    cloud_init_user_data: str,
    cpu_cores: int,
    memory: str,
    image: str,
) -> Dict[str, Any]:
    return {
        "apiVersion": "kubevirt.io/v1",
        "kind": "VirtualMachine",
        "metadata": {
            "name": vm_name,
            "namespace": namespace
        },
        "spec": {
            "running": True,
            "template": {
                "spec": {
                    "domain": {
                        "cpu": {"cores": cpu_cores},
                        "resources": {"requests": {"memory": memory}},
                        "devices": {
                            "disks": [
                                {
                                    "name": "rootdisk",
                                    "disk": {"bus": "virtio"},
                                },
                                {
                                    "name": "cloudinitdisk",
                                    "disk": {"bus": "virtio"},
                                },
                            ],
                            "interfaces": [
                                {"name": "default", "masquerade": {}}
                            ]
                        }
                    },
                    "networks": [{"name": "default", "pod": {}}],
                    "volumes": [
                        {
                            "name": "rootdisk",
                            "containerDisk": {"image": image},
                        },
                        {
                            "name": "cloudinitdisk",
                            "cloudInitNoCloud": {
                                "userData": cloud_init_user_data
                            }
                        }
                    ]
                }
            }
        }
    }


class OpenShift(object):
    """Provision an OpenShift cluster"""

    def __init__(
            self, name: str, os_type: str = "ubuntu", os_version: str = "22.04"
        ) -> None:
        """Initialize the OpenShift object

        :param name: The fully-qualified domain name of the machine to manage
        :param os_type: The OS type to deploy (e.g. "ubuntu")
        :param os_version: The OS version to deploy (e.g. "22.04")
        """
        self._objects_api, self._core_api = get_session()

        self.group = "kubevirt.io"
        self.version = "v1"
        self.plural = "virtualmachines"

        self.remote = Remote(misc.canonicalize_hostname(name))
        self.name = self.remote.hostname
        self.shortname = self.remote.shortname

        self.namespace = get_namespace()
        self.os_type = os_type
        self.os_version = os_version

        self.log = log.getChild(self.shortname)

    def create(
        self,
        cpu_cores: int = 2,
        memory: str = "2Gi",
        image: str = "ubuntu:22.04",
    ) -> Tuple[str, str]:
        """Create the OpenShift cluster

        :param cpu_cores: The number of CPU cores to provision
        :param memory: The amount of memory to provision
        :param image: The image to provision

        :returns: A tuple containing the name and IP address of the VM
            (name, ip)
        """
        self.provision(cpu_cores=cpu_cores, memory=memory, image=image)
        self._wait_for_status("Running")
        ip = self._wait_for_ip_address()
        
        return self.name, ip


    def provision(self, cpu_cores: int, memory: str, image: str) -> None:
        """Provisions a VM in the namespace."""
        print(
            f"Provisioning Virtual Machine {self.name} "
            f"in namespace {self.namespace} with CPU cores {cpu_cores}, "
            f"memory {memory}, and image {image} ..."
        )
        user_data = self._get_user_data()
        if not user_data:
            raise RuntimeError("Failed to get user data")

        manifest = get_vm_manifest(
            namespace=self.namespace,
            vm_name=self.name,
            cloud_init_user_data=user_data,
            cpu_cores=cpu_cores,
            memory=memory,
            image=image
        )
        log.info(f'Manifest: {manifest}')
        try:
            response = self._objects_api.create_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=self.namespace,
                plural=self.plural,
                body=manifest,
            )
            log.info(f'Response: {response}')
            return response
        except client.ApiException as e:
            print(
                f"Failed to provision Virtual Machine {self.name} "
                f"in namespace {self.namespace} due to error:\n{str(e)}"
            )
            raise

    def release(self):
        """Release the OpenShift cluster"""
        self.delete()
        self._wait_for_status("Deleted")

    def delete(self):
        """Deletes a VM in the namespace."""
        try:
            log.info(
                f"Deleting Virtual Machine {self.name} "
                f"in namespace {self.namespace} ..."
            )
            self._objects_api.delete_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=self.namespace,
                plural=self.plural,
                name=self.name
            )
            log.info(
                f"Successfully deleted Virtual Machine {self.name} "
                f"in namespace {self.namespace} ..."
            )
        except client.ApiException as e:
            log.error(
                f"Failed to delete Virtual Machine {self.name} "
                f"in namespace {self.namespace} due to error:\n{str(e)}"
            )
            raise

    def _get_user_data(self) -> Optional[str]:
        """Get user data for cloud-init

        :returns: cloud-init user data string, or None if no template is configured
        """
        user_data_template = config.openshift.get("user_data")
        if not user_data_template:
            return None

        user_data_path = user_data_template.format(
            os_type=self.os_type, os_version=self.os_version
        )
        with open(user_data_path, "r") as f:
            return f.read()


    def _get_ip_from_vmi(self, vmi: dict) -> str | None:
        """Return the routable IP for a masquerade/pod-network VMI.
        
        :param vmi: The VMI object

        :returns: The IP address of the VM, 
            or None if the VMI does not have an routable IP address
        """
        status = vmi.get("status") or {}
        for iface in status.get("interfaces") or []:
            ip = iface.get("ipAddress")
            if ip:
                return ip

            ip_addresses = iface.get("ipAddresses") or []
            if ip_addresses:
                return ip_addresses[0]

        return None

    def _get_ip_from_launcher_pod(self) -> str | None:
        """Return the virt-launcher pod IP for the VM."""
        pods = self.core_api.list_namespaced_pod(
            namespace=self.namespace,
            label_selector=f"vm.kubevirt.io/name={self.name}",
        )
        for pod in pods.items:
            if pod.status.pod_ip:
                return pod.status.pod_ipafter

        return None

    def _wait_for_ip_address(
        self, timeout: int = 300, interval: int = 5,
    ) -> str:
        """Poll until the VM IP address is available or timeout expires.

        :param timeout: The maximum time to wait for the IP address
        :param interval: The time to wait between polling attempts

        :returns: The IP address of the VM
        :raises: RuntimeError if the VM does not have an IP address
            within the timeout period
        """
        log.info(
            f"Waiting for IP address for Virtual Machine {self.name} "
            f"for {timeout} seconds ..."
        )
        with safe_while(sleep=interval, timeout=timeout) as proceed:
            while proceed():
                log.debug(
                    f"Polling for Virtual Machine {self.name} IP address ..."
                )
                try:
                    vmi = self._objects_api.get_namespaced_custom_object(
                        group=self.group,
                        version=self.version,
                        namespace=self.namespace,
                        plural=self.vmi_plural,
                        name=self.name,
                    )
                except client.ApiException as e:
                    if e.status != 404:
                        log.error(
                            f"Failed to get IP address for Virtual Machine "
                            f"{self.name} due to error:\n{str(e)}"
                        )
                        raise
                    vmi = None

                ip = (
                    self._get_ip_from_vmi(vmi)
                    or self._get_ip_from_launcher_pod()
                )
                if not ip:
                    log.debug(
                        f"Virtual Machine {self.name} has no IP address yet, "
                        f"waiting for {interval} seconds ..."
                    )
                    continue

                log.info(
                    f"Virtual Machine {self.name} has IP address: {ip}"
                )
                return ip

        raise RuntimeError(
            f"Virtual Machine {self.name} has no IP address after "
            f"{timeout} seconds of polling"
        )

    def _wait_for_status(
        self, status: str = "Running", timeout: int = 300, interval: int = 5,
    ) -> None:
        """Poll until the VM reaches the desired status or timeout expires.
        
        :param status: The desired status to wait for
        :param timeout: The maximum time to wait for the status
        :param interval: The time to wait between status checks

        :raises: RuntimeError if the VM does not reach the desired status
            within the timeout period
        """
        log.info(
            f"Waiting for Virtual Machine {self.name} to reach status "
            f"{status} within {timeout}s ..."
        )
        with safe_while(sleep=interval, timeout=timeout) as proceed:
            while proceed():
                log.debug(
                    f"Polling for Virtual Machine {self.name} status ..."
                )
                vm = self._objects_api.get_namespaced_custom_object(
                    group=self.group,
                    version=self.version,
                    namespace=self.namespace,
                    plural=self.plural,
                    name=self.name,
                )
                _status = (
                    vm.get("status", {})
                    .get("printableStatus", "Unknown")
                    .lower()
                )
                if _status == status.lower():
                    log.info(
                        f"Virtual Machine {self.name} reached status {_status}"
                    )
                    return

                log.debug(
                    f"Virtual Machine {self.name} is in status {_status},"
                    f"waiting {interval}s to reach status {status} ..."
                )

        raise RuntimeError(
            f"Virtual Machine {self.name} is in status '{_status}' "
            f"after {timeout}s of polling, expected status is '{status}'"
        )
