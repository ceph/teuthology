import logging
import os
import base64
import hashlib
import tempfile

import yaml
from kubernetes import client
from typing import List, Optional, Tuple, Dict, Any, Union

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


def get_udn_name() -> str:
    """Return the Multus/UserDefinedNetwork name for test VMs.

    Empty string disables Multus attachment (masquerade-only).
    """
    conf = config.get("openshift", {})
    if "udn_name" in conf:
        return conf.get("udn_name") or ""
    return "teuthology-net"


def get_udn_binding() -> str:
    """Return the KubeVirt interface binding for the UDN NIC."""
    return config.get("openshift", {}).get("udn_binding", "l2bridge")


def get_session() -> Tuple[client.CustomObjectsApi, client.CoreV1Api]:
    """Get a session for communicating with the OpenShift API.

    Authenticates with openshift.server and openshift.token from
    ~/.teuthology.yaml (ServiceAccount), not ~/.kube/config.
    """
    if not enabled():
        raise RuntimeError("OpenShift is not configured!")

    configuration = _client_configuration()
    token = configuration.api_key.get("authorization") or ""
    prefix = configuration.api_key_prefix.get("authorization") or "Bearer"
    api_client = client.ApiClient(
        configuration,
        header_name="Authorization",
        header_value=f"{prefix} {token}".strip(),
    )
    return client.CustomObjectsApi(api_client), client.CoreV1Api(api_client)


def _write_ca_file(ca_data: str) -> str:
    """Decode certificate_authority_data and write a PEM file.

    The path is derived from a hash of the CA bytes so parallel jobs and
    processes share the same file without a module-level cache. The write
    is atomic (temp file then replace).
    """
    pem = base64.b64decode(ca_data)
    digest = hashlib.sha256(pem).hexdigest()[:16]
    path = os.path.join(
        tempfile.gettempdir(), f"teuthology-ocp-ca-{digest}.crt"
    )
    if os.path.isfile(path) and os.path.getsize(path) == len(pem):
        return path
    fd, tmp = tempfile.mkstemp(
        prefix="teuthology-ocp-ca-", suffix=".crt",
        dir=tempfile.gettempdir(),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(pem)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def _client_configuration() -> client.Configuration:
    """Build a kubernetes client Configuration from teuthology.yaml."""
    server = str(_openshift_required("server")).rstrip("/")
    token = str(_openshift_required("token"))
    configuration = client.Configuration()
    configuration.host = server
    configuration.api_key_prefix["authorization"] = "Bearer"
    configuration.api_key["authorization"] = token
    ca_data = (config.get("openshift", {}) or {}).get(
        "certificate_authority_data"
    )
    if ca_data:
        configuration.ssl_ca_cert = _write_ca_file(str(ca_data))
        configuration.verify_ssl = True
    else:
        configuration.verify_ssl = False
    return configuration


def get_datasource_namespace() -> str:
    """Return the namespace for OpenShift virtualization OS DataSources.

    Prefers ``openshift.datasource_namespace`` when set; otherwise uses the
    guest VM namespace (``openshift.namespace``).
    """
    conf = config.get("openshift", {}) or {}
    ns = conf.get("datasource_namespace")
    if ns:
        return str(ns)
    return str(conf.get("namespace") or "")


def _openshift_required(key: str) -> Any:
    """Return a required openshift.* key from ~/.teuthology.yaml."""
    value = (config.get("openshift", {}) or {}).get(key)
    if value is None or value == "":
        raise RuntimeError(
            f"openshift.{key} is required in ~/.teuthology.yaml"
        )
    return value


def get_root_storage_size() -> str:
    """Return the root disk size for provisioned VMs."""
    return _volume_storage_size(_openshift_required("root_storage_size"))


def get_root_storage_class() -> str:
    """Return the StorageClass for the guest root disk."""
    return str(_openshift_required("root_storage_class"))


def get_data_storage_class() -> str:
    """Return the StorageClass for extra guest disks."""
    return str(_openshift_required("data_storage_class"))


def get_vcpus() -> int:
    """Return guest vCPU count from teuthology.yaml."""
    return int(_openshift_required("vcpus"))


def get_ram() -> str:
    """Return guest RAM from teuthology.yaml as a Kubernetes quantity."""
    return _volume_storage_size(_openshift_required("ram"))


def _storage_spec(size: str, storage_class: str = "") -> Dict[str, Any]:
    """Build a CDI/KubeVirt storage spec, optionally pinning a StorageClass."""
    spec: Dict[str, Any] = {
        "resources": {
            "requests": {
                "storage": size,
            },
        },
    }
    if storage_class:
        spec["storageClassName"] = storage_class
    return spec


def _volume_storage_size(size: Any) -> str:
    """Normalize user-data volumes.size (GB int or Kubernetes quantity)."""
    if isinstance(size, str) and size:
        return size if size[-1].isalpha() else f"{size}Gi"
    return f"{int(size)}Gi"


def _normalize_volumes_spec(
    volumes_cfg: Any, source: str = "user-data"
) -> List[Dict[str, Any]]:
    """Return extra-disk groups as a list of {count, size} dicts.

    Accepts either a single mapping or a list of mappings::

        volumes:
          count: 3
          size: 10

        volumes:
          - count: 3
            size: 15
          - count: 2
            size: 20
    """
    if not volumes_cfg:
        return []
    if isinstance(volumes_cfg, dict):
        groups = [volumes_cfg]
    elif isinstance(volumes_cfg, list):
        groups = volumes_cfg
    else:
        raise RuntimeError(
            f"Invalid volumes spec in {source}: expected a mapping or list"
        )

    normalized: List[Dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            raise RuntimeError(
                f"Invalid volumes entry in {source}: expected count/size mapping"
            )
        count = int(group.get("count", 0) or 0)
        if count < 0:
            raise RuntimeError(f"Invalid volumes count {count} in {source}")
        if count == 0:
            continue
        normalized.append({
            "count": count,
            "size": group.get("size", 1),
        })
    return normalized


def _normalize_datasource_spec(
    spec: Any, source: str = "user-data"
) -> Dict[str, str]:
    """Return ``{name, namespace?}`` from a user-data ``datasource`` key.

    Accepts either a bare name or a mapping::

        datasource: rocky-10

        datasource:
          name: centos-stream9
          namespace: openshift-virtualization-os-images
    """
    if spec is None or spec == "":
        raise RuntimeError(
            f"Missing required datasource in {source}"
        )
    if isinstance(spec, str):
        return {"name": spec}
    if isinstance(spec, dict):
        name = spec.get("name")
        if not name:
            raise RuntimeError(
                f"Invalid datasource in {source}: expected name"
            )
        out: Dict[str, str] = {"name": str(name)}
        namespace = spec.get("namespace")
        if namespace:
            out["namespace"] = str(namespace)
        return out
    raise RuntimeError(
        f"Invalid datasource in {source}: expected a name or mapping"
    )


def parse_user_data_file(
    path: str,
) -> Tuple[str, List[Dict[str, Any]], Dict[str, str]]:
    """Load an OCP user-data file and split cloud-init from teuthology keys.

    ``volumes`` and ``datasource`` are teuthology-only and are not passed to
    the guest. Remaining YAML is sent as cloud-init user-data.

    :returns: (cloud-init user-data, extra volume groups, datasource spec)
    """
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}

    volumes = _normalize_volumes_spec(data.pop("volumes", None), source=path)
    datasource = _normalize_datasource_spec(
        data.pop("datasource", None), source=path
    )
    cloud_init = "#cloud-config\n" + yaml.safe_dump(
        data, default_flow_style=False, sort_keys=False
    )
    return cloud_init, volumes, datasource


def get_vm_manifest(
    namespace: str,
    vm_name: str,
    cloud_init_user_data: str,
    cpu_cores: int,
    memory: str,
    datasource: str,
    datasource_namespace: str,
    root_storage_size: str,
    udn_name: str = "",
    mac_address: Optional[str] = None,
    udn_binding: str = "l2bridge",
    extra_volumes: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    root_storage_class: str = "",
    data_storage_class: str = "",
) -> Dict[str, Any]:
    rootdisk_name = f"{vm_name}-rootdisk"
    interfaces: List[Dict[str, Any]] = [
        {"name": "default", "masquerade": {}},
    ]
    networks: List[Dict[str, Any]] = [
        {"name": "default", "pod": {}},
    ]

    if udn_name:
        udn_iface: Dict[str, Any] = {
            "name": udn_name,
            "binding": {"name": udn_binding},
        }
        if mac_address:
            udn_iface["macAddress"] = mac_address
        interfaces.append(udn_iface)
        networks.append({
            "name": udn_name,
            "multus": {"networkName": udn_name},
        })

    data_volume_templates: List[Dict[str, Any]] = [
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
                "storage": _storage_spec(root_storage_size, root_storage_class),
            },
        },
    ]
    # Attach cloud-init as a SATA CD-ROM (not a virtio disk). As a tiny
    # virtio disk it appears as e.g. vdb and ceph-cm-ansible's zap_disks
    # task tries to dd 110MiB onto it ("No space left on device"). As sr*
    # it is skipped by zap_skip_disks (match ^(loop|ram|sr)).
    disks: List[Dict[str, Any]] = [
        {
            "name": rootdisk_name,
            "disk": {"bus": "virtio"},
        },
        {
            "name": "cloudinitdisk",
            "cdrom": {"bus": "sata"},
        },
    ]
    volumes: List[Dict[str, Any]] = [
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

    extra_groups = _normalize_volumes_spec(extra_volumes)
    vol_index = 0
    for group in extra_groups:
        extra_size = _volume_storage_size(group.get("size", 1))
        for _ in range(int(group["count"])):
            vol_name = f"{vm_name}-vol-{vol_index}"
            vol_index += 1
            data_volume_templates.append({
                "metadata": {
                    "name": vol_name,
                },
                "spec": {
                    "source": {
                        "blank": {},
                    },
                    "storage": _storage_spec(extra_size, data_storage_class),
                },
            })
            disks.append({
                "name": vol_name,
                "disk": {"bus": "virtio"},
            })
            volumes.append({
                "name": vol_name,
                "dataVolume": {
                    "name": vol_name,
                },
            })

    return {
        "apiVersion": "kubevirt.io/v1",
        "kind": "VirtualMachine",
        "metadata": {
            "name": vm_name,
            "namespace": namespace
        },
        "spec": {
            "running": True,
            "dataVolumeTemplates": data_volume_templates,
            "template": {
                "spec": {
                    "domain": {
                        "cpu": {"cores": cpu_cores},
                        "resources": {"requests": {"memory": memory}},
                        "devices": {
                            "disks": disks,
                            "interfaces": interfaces,
                        }
                    },
                    "networks": networks,
                    "volumes": volumes,
                }
            }
        }
    }


class OpenShift(object):
    """Provision an OpenShift Virtualization VM"""

    def __init__(
            self, name: str, os_type: str = "ubuntu", os_version: str = "22.04"
        ) -> None:
        """Initialize the OpenShift object

        :param name: The short or fully-qualified name of the machine to manage
        :param os_type: The OS type to deploy (e.g. "ubuntu")
        :param os_version: The OS version to deploy (e.g. "22.04")
        """
        # Lazy import avoids circular dependency with orchestra.remote → lock → provision
        from teuthology.orchestra.remote import Remote

        self._objects_api, self._core_api = get_session()

        self.group = "kubevirt.io"
        self.version = "v1"
        self.plural = "virtualmachines"
        self.vmi_plural = "virtualmachineinstances"

        self.remote = Remote(misc.canonicalize_hostname(name))
        # FQDN used for inventory/SSH; shortname is the VirtualMachine object name
        self.name = self.remote.hostname
        self.shortname = self.remote.shortname
        self.vm_name = self.shortname

        self.namespace = get_namespace()
        self.udn_name = get_udn_name()
        self.udn_binding = get_udn_binding()
        self.os_type = os_type
        self.os_version = os_version
        self.mac_address = self._get_mac_address()

        self.log = log.getChild(self.shortname)

    def _get_mac_address(self) -> Optional[str]:
        """Return the paddles MAC for this node, if registered."""
        # Lazy import avoids circular dependency with lock.query → provision
        from teuthology.lock import query
        status = query.get_status(self.name) or query.get_status(self.shortname)
        mac = (status or {}).get("mac_address") or None
        if mac:
            return mac.strip()
        return None

    def create(
        self,
        cpu_cores: Optional[int] = None,
        memory: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Create the VirtualMachine and wait until it is Running with an IP.

        cpu_cores and memory default to required openshift.vcpus and
        openshift.ram in ~/.teuthology.yaml.

        :param cpu_cores: The number of CPU cores to provision
        :param memory: The amount of memory to provision

        :returns: A tuple containing the FQDN and IP address of the VM
            (name, ip)
        """
        if cpu_cores is None:
            cpu_cores = get_vcpus()
        if memory is None:
            memory = get_ram()
        if not self.delete():
            self._wait_for_status("Deleted")
        self.provision(cpu_cores=cpu_cores, memory=memory)
        self._wait_for_status("Running")
        ip = self._wait_for_ip_address()
        return self.name, ip

    def provision(self, cpu_cores: int, memory: str) -> None:
        """Provisions a VM in the namespace."""
        if self.udn_name and not self.mac_address:
            raise RuntimeError(
                f"OpenShift UDN '{self.udn_name}' is configured but paddles "
                f"node '{self.shortname}' has no mac_address. Register a MAC "
                f"in paddles and dhcpGateway.dhcpHosts before locking."
            )

        user_data, extra_volumes, datasource_spec = self._get_user_data()
        if not user_data:
            raise RuntimeError("Failed to get user data")

        manifest = get_vm_manifest(
            namespace=self.namespace,
            vm_name=self.vm_name,
            cloud_init_user_data=user_data,
            cpu_cores=cpu_cores,
            memory=memory,
            datasource=datasource_spec["name"],
            datasource_namespace=(
                datasource_spec.get("namespace") or get_datasource_namespace()
            ),
            root_storage_size=get_root_storage_size(),
            udn_name=self.udn_name,
            mac_address=self.mac_address,
            udn_binding=self.udn_binding,
            extra_volumes=extra_volumes,
            root_storage_class=get_root_storage_class(),
            data_storage_class=get_data_storage_class(),
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
                f"Failed to provision Virtual Machine {self.vm_name} "
                f"in namespace {self.namespace} due to error:\n{str(e)}"
            )
            raise

    def release(self):
        """Release the OpenShift Virtual Machine"""
        if not self.delete():
            self._wait_for_status("Deleted")

    def delete(self) -> bool:
        """Deletes a VM in the namespace.

        :returns: True if the VM is already absent, False if delete was issued
        """
        try:
            log.info(
                f"Deleting Virtual Machine {self.vm_name} "
                f"in namespace {self.namespace} ..."
            )
            self._objects_api.delete_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=self.namespace,
                plural=self.plural,
                name=self.vm_name
            )
            log.info(
                f"Successfully deleted Virtual Machine {self.vm_name} "
                f"in namespace {self.namespace} ..."
            )
            return False
        except client.ApiException as e:
            if e.status == 404:
                log.info(
                    f"Virtual Machine {self.vm_name} not found; "
                    f"already deleted"
                )
                return True
            log.error(
                f"Failed to delete Virtual Machine {self.vm_name} "
                f"in namespace {self.namespace} due to error:\n{str(e)}"
            )
            raise

    def _get_user_data(
        self,
    ) -> Tuple[Optional[str], List[Dict[str, Any]], Dict[str, str]]:
        """Load OS-specific OCP user-data (cloud-init, volumes, datasource).

        Login user, ssh_authorized_keys, volumes, and datasource come from
        teuthology/ocp/user_data/ files.

        :returns: (cloud-init user-data, extra volume groups, datasource spec)
        """
        user_data_template = config.openshift.get("user_data")
        if not user_data_template:
            return None, [], {}

        user_data_path = user_data_template.format(
            os_type=self.os_type, os_version=self.os_version
        )
        if not os.path.exists(user_data_path):
            raise RuntimeError(
                f"OpenShift user_data template not found: {user_data_path}"
            )

        return parse_user_data_file(user_data_path)

    def _iface_ips(self, iface: dict) -> List[str]:
        ips: List[str] = []
        ip = iface.get("ipAddress")
        if ip:
            ips.append(ip)
        for candidate in iface.get("ipAddresses") or []:
            if candidate and candidate not in ips:
                ips.append(candidate)
        return ips

    def _get_ip_from_vmi(self, vmi: dict) -> str | None:
        """Return the preferred guest IP from a VMI status.

        When a UDN/Multus network is configured, only return an address from
        that interface. Falling back to the default masquerade/pod IP is wrong
        for teuthology: SSH and DNS use the UDN (e.g. teuthology-net), and
        accepting the pod IP early races dhcp/DNS registration.

        Without a UDN, return the first interface address.
        """
        if not vmi:
            return None
        status = vmi.get("status") or {}
        interfaces = status.get("interfaces") or []

        if self.udn_name:
            for iface in interfaces:
                if iface.get("name") == self.udn_name:
                    ips = self._iface_ips(iface)
                    if ips:
                        return ips[0]
            return None

        for iface in interfaces:
            ips = self._iface_ips(iface)
            if ips:
                return ips[0]

        return None

    def _get_ip_from_launcher_pod(self) -> str | None:
        """Return the virt-launcher pod IP for the VM."""
        pods = self._core_api.list_namespaced_pod(
            namespace=self.namespace,
            label_selector=f"vm.kubevirt.io/name={self.vm_name}",
        )
        for pod in pods.items:
            if pod.status.pod_ip:
                return pod.status.pod_ip

        return None

    def _wait_for_ip_address(
        self, timeout: int = 600, interval: int = 5,
    ) -> str:
        """Poll until the VM IP address is available or timeout expires.

        When ``udn_name`` is set, wait specifically for that interface's IP
        (not the default masquerade/pod address or virt-launcher pod IP).

        :param timeout: The maximum time to wait for the IP address
        :param interval: The time to wait between polling attempts

        :returns: The IP address of the VM
        :raises: RuntimeError if the VM does not have an IP address
            within the timeout period
        """
        if self.udn_name:
            log.info(
                f"Waiting for {self.udn_name} IP address for Virtual Machine "
                f"{self.vm_name} for {timeout} seconds ..."
            )
        else:
            log.info(
                f"Waiting for IP address for Virtual Machine {self.vm_name} "
                f"for {timeout} seconds ..."
            )
        with safe_while(sleep=interval, timeout=timeout) as proceed:
            while proceed():
                log.debug(
                    f"Polling for Virtual Machine {self.vm_name} IP address ..."
                )
                try:
                    vmi = self._objects_api.get_namespaced_custom_object(
                        group=self.group,
                        version=self.version,
                        namespace=self.namespace,
                        plural=self.vmi_plural,
                        name=self.vm_name,
                    )
                except client.ApiException as e:
                    if e.status != 404:
                        log.error(
                            f"Failed to get IP address for Virtual Machine "
                            f"{self.vm_name} due to error:\n{str(e)}"
                        )
                        raise
                    vmi = None

                ip = self._get_ip_from_vmi(vmi)
                if not ip and not self.udn_name:
                    ip = self._get_ip_from_launcher_pod()
                if not ip:
                    if self.udn_name:
                        log.debug(
                            f"Virtual Machine {self.vm_name} has no "
                            f"{self.udn_name} IP yet, waiting for "
                            f"{interval} seconds ..."
                        )
                    else:
                        log.debug(
                            f"Virtual Machine {self.vm_name} has no IP "
                            f"address yet, waiting for {interval} seconds ..."
                        )
                    continue

                log.info(
                    f"Virtual Machine {self.vm_name} has IP address: {ip}"
                )
                return ip

        if self.udn_name:
            raise RuntimeError(
                f"Virtual Machine {self.vm_name} has no {self.udn_name} IP "
                f"after {timeout} seconds of polling"
            )
        raise RuntimeError(
            f"Virtual Machine {self.vm_name} has no IP address after "
            f"{timeout} seconds of polling"
        )

    def _wait_for_status(
        self, status: str = "Running", timeout: int = 600, interval: int = 5,
    ) -> None:
        """Poll until the VM reaches the desired status or timeout expires.

        :param status: The desired status to wait for
        :param timeout: The maximum time to wait for the status
        :param interval: The time to wait between status checks

        :raises: RuntimeError if the VM does not reach the desired status
            within the timeout period
        """
        log.info(
            f"Waiting for Virtual Machine {self.vm_name} to reach status "
            f"{status} within {timeout}s ..."
        )
        _status = "Unknown"
        with safe_while(sleep=interval, timeout=timeout) as proceed:
            while proceed():
                log.debug(
                    f"Polling for Virtual Machine {self.vm_name} status ..."
                )
                try:
                    vm = self._objects_api.get_namespaced_custom_object(
                        group=self.group,
                        version=self.version,
                        namespace=self.namespace,
                        plural=self.plural,
                        name=self.vm_name,
                    )
                except client.ApiException as e:
                    if e.status == 404 and status.lower() == "deleted":
                        log.info(
                            f"Virtual Machine {self.vm_name} is deleted"
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
                        f"Virtual Machine {self.vm_name} reached status {_status}"
                    )
                    return

                log.debug(
                    f"Virtual Machine {self.vm_name} is in status {_status},"
                    f"waiting {interval}s to reach status {status} ..."
                )

        raise RuntimeError(
            f"Virtual Machine {self.vm_name} is in status '{_status}' "
            f"after {timeout}s of polling, expected status is '{status}'"
        )
