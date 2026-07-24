import logging

from kubernetes import client, config as kubernetes_config
from typing import List, Optional, Tuple, Dict, Any

from teuthology.orchestra.remote import Remote
from teuthology.config import config
from teuthology.contextutil import safe_while
from teuthology import misc

log = logging.getLogger(__name__)

AVAILABLE_DATASOURCES = frozenset({
    "centos-stream9",
    "centos-stream10",
    "fedora",
    "rhel7",
    "rhel8",
    "rhel9",
    "rhel10",
    "win10",
    "win11",
    "win2k16",
    "win2k19",
    "win2k22",
    "win2k25",
})


def _normalize_os_type(os_type: str) -> str:
    return os_type.lower().replace('_', '-')


def _major_version(os_version: str) -> str:
    version = os_version.lower().replace('.stream', '')
    if version.startswith('2k'):
        return version
    if len(version) == 4 and version.isdigit() and version.startswith('20'):
        return f"2k{version[2:]}"
    return version.split('.')[0]


def _resolve_datasource_name(os_type: str, os_version: str) -> Optional[str]:
    """Map teuthology os_type/os_version to a cluster DataSource name."""
    os_type = _normalize_os_type(os_type)
    version = os_version.lower()

    if os_type in ('centos', 'centos-stream'):
        major = _major_version(version)
        if major == '9':
            return 'centos-stream9'
        if major == '10':
            return 'centos-stream10'
    elif os_type == 'fedora':
        return 'fedora'
    elif os_type == 'rhel':
        major = _major_version(version)
        return f'rhel{major}'
    elif os_type in ('windows', 'win'):
        windows_map = {
            '10': 'win10',
            '11': 'win11',
            '16': 'win2k16',
            '19': 'win2k19',
            '22': 'win2k22',
            '25': 'win2k25',
            '2016': 'win2k16',
            '2019': 'win2k19',
            '2022': 'win2k22',
            '2025': 'win2k25',
            '2k16': 'win2k16',
            '2k19': 'win2k19',
            '2k22': 'win2k22',
            '2k25': 'win2k25',
        }
        return (
            windows_map.get(version)
            or windows_map.get(_major_version(version))
        )

    return None


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


def get_datasource_namespace() -> str:
    """Return the namespace for OpenShift virtualization OS DataSources."""
    return config.get("openshift", {}).get(
        "datasource_namespace", "openshift-virtualization-os-images",
    )


def get_storage_size() -> str:
    """Return the root disk size for provisioned VMs."""
    return config.get("openshift", {}).get("storage_size", "30Gi")


def get_vm_manifest(
    namespace: str,
    vm_name: str,
    cloud_init_user_data: str,
    cpu_cores: int,
    memory: str,
    datasource: str,
    datasource_namespace: str,
    storage_size: str,
) -> Dict[str, Any]:
    rootdisk_name = "rootdisk"
    return {
        "apiVersion": "kubevirt.io/v1",
        "kind": "VirtualMachine",
        "metadata": {
            "name": vm_name,
            "namespace": namespace
        },
        "spec": {
            "running": True,
            "dataVolumeTemplates": [
                {
                    "metadata": {
                        "name": rootdisk_name,
                    },
                    "spec": {
                        "sourceRef": {
                            "kind": "DataSource",
                            "name": datasource,
                            "namespace": datasource_namespace,
                        },
                        "storage": {
                            "resources": {
                                "requests": {
                                    "storage": storage_size,
                                },
                            },
                        },
                    },
                },
            ],
            "template": {
                "spec": {
                    "domain": {
                        "cpu": {"cores": cpu_cores},
                        "resources": {"requests": {"memory": memory}},
                        "devices": {
                            "disks": [
                                {
                                    "name": rootdisk_name,
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
                            "name": rootdisk_name,
                            "dataVolume": {
                                "name": rootdisk_name,
                            },
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
        self.vmi_plural = "virtualmachineinstances"

        self.remote = Remote(misc.canonicalize_hostname(name))
        self.name = self.remote.hostname
        self.shortname = self.remote.shortname

        self.namespace = get_namespace()
        self.os_type = os_type
        self.os_version = os_version

        self.log = log.getChild(self.shortname)

    def get_datasource(
        self,
        os_type: Optional[str] = None,
        os_version: Optional[str] = None,
    ) -> str:
        """Return the OpenShift virtualization DataSource for the given OS.

        :param os_type: OS type (defaults to self.os_type)
        :param os_version: OS version (defaults to self.os_version)
        :returns: DataSource name from openshift-virtualization-os-images
        :raises: RuntimeError if no matching datasource is available
        """
        os_type = os_type or self.os_type
        os_version = os_version or self.os_version
        key = f"{os_type}-{os_version}"
        datasources = config.openshift.get("datasources", {})
        if isinstance(datasources, dict) and key in datasources:
            datasource = datasources[key]
        else:
            datasource = _resolve_datasource_name(os_type, os_version)

        if not datasource:
            raise RuntimeError(
                f"No OpenShift virtualization datasource mapping for "
                f"os_type={os_type!r} os_version={os_version!r}. "
                f"Available datasources: {sorted(AVAILABLE_DATASOURCES)}"
            )
        if datasource not in AVAILABLE_DATASOURCES:
            raise RuntimeError(
                f"Datasource {datasource!r} is not available on the cluster. "
                f"Available datasources: {sorted(AVAILABLE_DATASOURCES)}"
            )
        return datasource

    def create(
        self,
        cpu_cores: int = 2,
        memory: str = "2Gi",
    ) -> Tuple[str, str]:
        """Create the OpenShift cluster

        :param cpu_cores: The number of CPU cores to provision
        :param memory: The amount of memory to provision

        :returns: A tuple containing the name and IP address of the VM
            (name, ip)
        """
        self.provision(cpu_cores=cpu_cores, memory=memory)
        self._wait_for_status("Running")
        ip = self._wait_for_ip_address()
        return self.name, ip

    def provision(self, cpu_cores: int, memory: str) -> None:
        """Provisions a VM in the namespace."""
        datasource = self.get_datasource()
        user_data = self._get_user_data()
        if not user_data:
            raise RuntimeError("Failed to get user data")

        manifest = get_vm_manifest(
            namespace=self.namespace,
            vm_name=self.name,
            cloud_init_user_data=user_data,
            cpu_cores=cpu_cores,
            memory=memory,
            datasource=datasource,
            datasource_namespace=get_datasource_namespace(),
            storage_size=get_storage_size(),
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
        if not self.delete():
            self._wait_for_status("Deleted")

    def delete(self) -> bool:
        """Deletes a VM in the namespace.

        :returns: True if the VM is already absent, False if delete was issued
        """
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
            return False
        except client.ApiException as e:
            if e.status == 404:
                log.info(
                    f"Virtual Machine {self.name} not found; "
                    f"already deleted"
                )
                return True
            log.error(
                f"Failed to delete Virtual Machine {self.name} "
                f"in namespace {self.namespace} due to error:\n{str(e)}"
            )
            raise

    def _get_user_data(self) -> Optional[str]:
        """Get user data for cloud-init

        :returns: cloud-init user data string, or None if unconfigured
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
        if not vmi:
            return None
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
        pods = self._core_api.list_namespaced_pod(
            namespace=self.namespace,
            label_selector=f"vm.kubevirt.io/name={self.name}",
        )
        for pod in pods.items:
            if pod.status.pod_ip:
                return pod.status.pod_ip

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
                try:
                    vm = self._objects_api.get_namespaced_custom_object(
                        group=self.group,
                        version=self.version,
                        namespace=self.namespace,
                        plural=self.plural,
                        name=self.name,
                    )
                except client.ApiException as e:
                    if e.status == 404 and status.lower() == "deleted":
                        log.info(
                            f"Virtual Machine {self.name} is deleted"
                        )
                        return
                    raise
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
