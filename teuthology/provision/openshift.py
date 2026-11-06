import logging
import os
import base64
import hashlib
import socket
import stat
import tempfile

import yaml
from typing import List, Optional, Tuple, Dict, Any

from paramiko import SSHException
from paramiko.ssh_exception import (
    BadHostKeyException,
    NoValidConnectionsError,
)

from teuthology.config import config
from teuthology.contextutil import safe_while
from teuthology.exceptions import MaxWhileTries
from teuthology.orchestra.opsys import OS
from teuthology import misc

log = logging.getLogger(__name__)

try:
    from kubernetes import client as _k8s_client
except ImportError:  # optional [openshift] extra
    _k8s_client = None


def _kubernetes_client():
    """Return the kubernetes.client module, or raise if not installed."""
    if _k8s_client is None:
        raise RuntimeError(
            "kubernetes is required for OpenShift provisioning; "
            "install teuthology with the [openshift] extra"
        )
    return _k8s_client


def _openshift_conf() -> Dict[str, Any]:
    """Return the openshift section from teuthology.yaml."""
    return config.get("openshift", {}) or {}


# Keys that must be present before OpenShift provisioning is considered enabled.
# ``volumes`` may be an empty list (no extra disks); the key must still exist.
_REQUIRED_CONF_KEYS = (
    "namespace",
    "machine_types",
    "server",
    "token",
    "user_data",
    "vcpus",
    "ram",
    "root_storage_size",
    "root_storage_class",
    "data_storage_class",
    "datasource_namespace",
    "datasources",
    "volumes",
    "udn_name",
    "ssh_authorized_keys",
)


def _unset_required_keys(conf: Dict[str, Any]) -> List[str]:
    """Return required openshift.* keys that are missing or empty."""
    unset: List[str] = []
    for key in _REQUIRED_CONF_KEYS:
        if key == "volumes":
            if "volumes" not in conf:
                unset.append(key)
            continue
        if not conf.get(key):
            unset.append(key)
    return unset


def enabled(warn: bool = False) -> bool:
    """Check if OpenShift is enabled

    :param warn: Whether to log a message containing unset parameters

    :returns: True if all required settings are present; False otherwise
    """
    if _k8s_client is None:
        if warn:
            log.warning(
                "OpenShift disabled; install the [openshift] extra "
                "(kubernetes package) to enable",
            )
        return False

    unset = _unset_required_keys(_openshift_conf())
    if unset and warn:
        log.warning(
            "OpenShift disabled; set the following config options to "
            f"enable: {' '.join(unset)}",
        )
    return not unset


def get_types() -> List[str]:
    """Fetch and parse OpenShift machine_types config.

    :returns: The list of OpenShift-configured machine types.
                Returns an empty list if OpenShift is not configured
    """
    if not enabled():
        return []
    types = _openshift_conf().get("machine_types", "")
    if isinstance(types, str):
        types = types.split(",")
    elif not isinstance(types, list):
        types = []
    return [type_ for type_ in types if type_]


def get_namespace() -> str:
    """Fetch and parse OpenShift namespace config.

    :returns: The OpenShift namespace.
    """
    if not enabled():
        return ""
    return _openshift_conf().get("namespace", "")


def get_udn_name() -> str:
    """Return the required Multus/UserDefinedNetwork name for test VMs.

    Masquerade-only (no UDN) is unsupported: teuthology connects by hostname
    and nothing maps that name to the pod/virt-launcher IP.
    """
    return str(_openshift_required("udn_name"))


def get_udn_binding() -> str:
    """Return the KubeVirt interface binding for the UDN NIC."""
    return _openshift_conf().get("udn_binding", "l2bridge")


def get_session() -> Tuple[Any, Any]:
    """Get a session for communicating with the OpenShift API.

    Authenticates with openshift.server and openshift.token from
    ~/.teuthology.yaml (ServiceAccount), not ~/.kube/config.
    """
    if not enabled():
        raise RuntimeError("OpenShift is not configured!")

    client = _kubernetes_client()
    api_client = client.ApiClient(_client_configuration())
    return client.CustomObjectsApi(api_client), client.CoreV1Api(api_client)


def _ca_cache_dir() -> str:
    """Return a per-user 0700 directory for OpenShift CA PEM files."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        base = os.path.expanduser(xdg)
    else:
        base = os.path.join(os.path.expanduser("~"), ".cache")
    path = os.path.join(base, "teuthology", "ocp-ca")
    os.makedirs(path, mode=0o700, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _write_ca_file(ca_data: str) -> str:
    """Decode certificate_authority_data and write a PEM file.

    Files live in a per-user cache directory (mode 0700), not shared /tmp.
    An existing file is reused only when its full contents match; a size-only
    check would allow another process to plant a different CA.
    """
    pem = base64.b64decode(ca_data)
    digest = hashlib.sha256(pem).hexdigest()[:16]
    cache_dir = _ca_cache_dir()
    path = os.path.join(cache_dir, f"{digest}.crt")
    try:
        st = os.lstat(path)
    except OSError:
        st = None
    if st is not None and stat.S_ISREG(st.st_mode):
        try:
            with open(path, "rb") as handle:
                if handle.read() == pem:
                    return path
        except OSError:
            pass
    fd, tmp = tempfile.mkstemp(
        prefix="teuthology-ocp-ca-", suffix=".crt",
        dir=cache_dir,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(pem)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def _client_configuration() -> Any:
    """Build a kubernetes client Configuration from teuthology.yaml.

    TLS is verified by default (system CAs, or ``certificate_authority_data``
    when set). Skipping verification requires an explicit
    ``insecure_skip_tls_verify: true`` and logs a warning.
    """
    client = _kubernetes_client()
    conf = _openshift_conf()
    server = str(_openshift_required("server")).rstrip("/")
    token = str(_openshift_required("token"))
    configuration = client.Configuration()
    configuration.host = server
    # kubernetes>=36 looks up BearerToken; api_key_prefix['authorization'] alone
    # is ignored and the request goes out unauthenticated (anonymous 403).
    configuration.api_key["BearerToken"] = token
    configuration.api_key_prefix["BearerToken"] = "Bearer"
    ca_data = conf.get("certificate_authority_data")
    if ca_data:
        configuration.ssl_ca_cert = _write_ca_file(str(ca_data))
    skip_tls = conf.get("insecure_skip_tls_verify")
    if skip_tls is True or str(skip_tls).lower() in ("1", "true", "yes"):
        log.warning(
            "openshift.insecure_skip_tls_verify is enabled; TLS certificate "
            "verification is disabled for the OpenShift API"
        )
        configuration.verify_ssl = False
    else:
        configuration.verify_ssl = True
    return configuration


def get_datasource_namespace() -> str:
    """Return the namespace for OpenShift virtualization OS DataSources."""
    return str(_openshift_required("datasource_namespace"))


def _openshift_required(key: str) -> Any:
    """Return a required openshift.* key from ~/.teuthology.yaml."""
    value = _openshift_conf().get(key)
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


def get_timeout(default: int = 900) -> int:
    """Return OpenShift wait timeout from teuthology.yaml (seconds).

    Used for VM status, IP, delete, and SSH readiness waits. Cloning a large
    root disk can exceed the old hardcoded 600s; set ``openshift.timeout``
    like ``maas.timeout``.
    """
    return int(_openshift_conf().get("timeout", default))


def get_volumes() -> List[Dict[str, Any]]:
    """Return extra blank-disk groups from openshift.volumes."""
    return _normalize_volumes_spec(
        _openshift_conf().get("volumes"),
        source="openshift.volumes",
    )


def get_datasource_name(os_type: str, os_version: str) -> str:
    """Return the DataSource name for an OS from openshift.datasources."""
    datasources = _openshift_required("datasources")
    if not isinstance(datasources, dict):
        raise RuntimeError(
            "openshift.datasources must be a mapping of "
            "'os_type/os_version' to DataSource name"
        )
    key = f"{os_type}/{os_version}"
    name = datasources.get(key)
    if not name:
        raise RuntimeError(
            f"openshift.datasources has no entry for '{key}'"
        )
    return str(name)


def _storage_spec(size: str, storage_class: str) -> Dict[str, Any]:
    """Build a CDI/KubeVirt storage spec with a required StorageClass."""
    if not storage_class:
        raise RuntimeError("storage_class is required for OpenShift volumes")
    return {
        "resources": {
            "requests": {
                "storage": size,
            },
        },
        "storageClassName": storage_class,
    }


def _volume_storage_size(size: Any) -> str:
    """Normalize volumes.size (GB int or Kubernetes quantity)."""
    if isinstance(size, str) and size:
        return size if size[-1].isalpha() else f"{size}Gi"
    return f"{int(size)}Gi"


def _normalize_volumes_spec(
    volumes_cfg: Any, source: str = "openshift.volumes"
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
    if volumes_cfg is None:
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


def get_ssh_authorized_keys() -> List[str]:
    """Return guest SSH public keys from openshift.ssh_authorized_keys."""
    value = _openshift_required("ssh_authorized_keys")
    if isinstance(value, str):
        keys = [value]
    elif isinstance(value, list):
        keys = value
    else:
        raise RuntimeError(
            "openshift.ssh_authorized_keys must be a string or list of strings"
        )
    out = [str(key).strip() for key in keys if str(key).strip()]
    if not out:
        raise RuntimeError(
            "openshift.ssh_authorized_keys must list at least one key"
        )
    return out


def _inject_ssh_authorized_keys(
    data: Dict[str, Any], keys: List[str]
) -> None:
    """Set ssh_authorized_keys on cloud-init users (or top-level)."""
    users = data.get("users")
    if isinstance(users, list) and users:
        for user in users:
            if isinstance(user, dict):
                user["ssh_authorized_keys"] = list(keys)
        return
    data["ssh_authorized_keys"] = list(keys)


def parse_user_data_file(
    path: str,
    ssh_authorized_keys: Optional[List[str]] = None,
) -> Tuple[str, Optional[str]]:
    """Load an OCP user-data file and split cloud-init from network-data.

    Templates are cloud-init only (plus optional ``network:``, which is sent as
    NoCloud ``networkData``). Extra disks and DataSource names come from
    ``openshift.volumes`` / ``openshift.datasources`` in teuthology.yaml.

    ``ssh_authorized_keys`` (from ``openshift.ssh_authorized_keys``) are
    injected into cloud-init users; templates should not hardcode them.

    :returns: (cloud-init user-data, network-data)
    """
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}

    if "volumes" in data or "datasource" in data:
        raise RuntimeError(
            f"{path} must not define teuthology-only keys "
            f"'volumes' or 'datasource'; set openshift.volumes / "
            f"openshift.datasources in teuthology.yaml instead"
        )

    network = data.pop("network", None)
    network_data = None
    if network is not None:
        network_data = yaml.safe_dump(
            network, default_flow_style=False, sort_keys=False
        )
    if ssh_authorized_keys:
        _inject_ssh_authorized_keys(data, ssh_authorized_keys)
    cloud_init = "#cloud-config\n" + yaml.safe_dump(
        data, default_flow_style=False, sort_keys=False
    )
    return cloud_init, network_data


def get_vm_manifest(
    namespace: str,
    vm_name: str,
    cloud_init_user_data: str,
    cpu_cores: int,
    memory: str,
    datasource: str,
    datasource_namespace: str,
    root_storage_size: str,
    root_storage_class: str,
    data_storage_class: str,
    udn_name: str = "",
    mac_address: Optional[str] = None,
    udn_binding: str = "l2bridge",
    extra_volumes: Optional[List[Dict[str, Any]]] = None,
    cloud_init_network_data: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a KubeVirt VirtualMachine manifest.

    Guests get a single Multus NIC on ``udn_name`` (no pod/masquerade
    interface). Dual NICs make the pod default route win and break lab
    connectivity off the front network (ceph tracker #80437).
    """
    if not udn_name:
        raise RuntimeError(
            "udn_name is required; OpenShift guests use a single Multus "
            "NIC (masquerade/pod networking is not supported)"
        )

    rootdisk_name = f"{vm_name}-rootdisk"
    udn_iface: Dict[str, Any] = {
        "name": udn_name,
        "binding": {"name": udn_binding},
    }
    if mac_address:
        udn_iface["macAddress"] = mac_address
    interfaces: List[Dict[str, Any]] = [udn_iface]
    networks: List[Dict[str, Any]] = [
        {
            "name": udn_name,
            "multus": {"networkName": udn_name},
        },
    ]

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
    cloud_init: Dict[str, str] = {"userData": cloud_init_user_data}
    if cloud_init_network_data:
        cloud_init["networkData"] = cloud_init_network_data

    volumes: List[Dict[str, Any]] = [
        {
            "name": rootdisk_name,
            "dataVolume": {
                "name": rootdisk_name,
            },
        },
        {
            "name": "cloudinitdisk",
            "cloudInitNoCloud": cloud_init,
        }
    ]

    # extra_volumes comes from openshift.volumes (already normalized)
    vol_index = 0
    for group in extra_volumes or []:
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
            "runStrategy": "Always",
            "dataVolumeTemplates": data_volume_templates,
            "template": {
                "spec": {
                    # Bridge/Multus NICs cannot live-migrate; testnodes are
                    # disposable, so do not block node drains.
                    "evictionStrategy": "None",
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
        self.group = "kubevirt.io"
        self.version = "v1"
        self.plural = "virtualmachines"
        self.vmi_plural = "virtualmachineinstances"

        # Keep hostnames via misc so release() does not need Remote/API/MAC.
        self.name = misc.canonicalize_hostname(name)
        self.shortname = misc.decanonicalize_hostname(self.name)
        self.vm_name = self.shortname
        self.namespace = get_namespace()
        self.os_type = os_type
        self.os_version = os_version

        self._objects_api = None
        self._core_api = None
        self._remote = None
        self._mac_address: Optional[str] = None
        self._mac_loaded = False
        self._udn_name: Optional[str] = None
        self._udn_binding: Optional[str] = None
        self.log = log.getChild(self.shortname)

    def _ensure_session(self) -> None:
        """Open the Kubernetes API session on first use."""
        if self._objects_api is None:
            self._objects_api, self._core_api = get_session()

    @property
    def objects_api(self) -> Any:
        self._ensure_session()
        return self._objects_api

    @property
    def core_api(self) -> Any:
        self._ensure_session()
        return self._core_api

    @property
    def remote(self) -> Any:
        """Lazy Remote used for SSH readiness checks during create()."""
        if self._remote is None:
            # Lazy import avoids circular dependency with orchestra.remote
            from teuthology.orchestra.remote import Remote
            self._remote = Remote(self.name)
        return self._remote

    @remote.setter
    def remote(self, value: Any) -> None:
        self._remote = value

    @property
    def udn_name(self) -> str:
        if self._udn_name is None:
            self._udn_name = get_udn_name()
        return self._udn_name

    @udn_name.setter
    def udn_name(self, value: str) -> None:
        self._udn_name = value

    @property
    def udn_binding(self) -> str:
        if self._udn_binding is None:
            self._udn_binding = get_udn_binding()
        return self._udn_binding

    @udn_binding.setter
    def udn_binding(self, value: str) -> None:
        self._udn_binding = value

    @property
    def mac_address(self) -> Optional[str]:
        if not self._mac_loaded:
            self._mac_address = self._get_mac_address()
            self._mac_loaded = True
        return self._mac_address

    @mac_address.setter
    def mac_address(self, value: Optional[str]) -> None:
        self._mac_address = value
        self._mac_loaded = True

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
        self.delete()
        self._wait_for_deleted()
        # On failure, unlock_many (used by lock_many after reimage errors) does
        # not call stop_node/release, so clean up the half-built VM here.
        try:
            self.provision(cpu_cores=cpu_cores, memory=memory)
            self._wait_for_status("Running")
            ip = self._wait_for_ip_address()
            # IP alone is not enough: each reimage mints new host keys, and
            # do_update_keys keyscan can race sshd/cloud-init. Match FOG/MAAS
            # by confirming SSH (and OS) before declaring success.
            self._wait_for_ready()
            return self.name, ip
        except Exception:
            self.log.exception(
                f"Failed to create Virtual Machine {self.vm_name}; cleaning up"
            )
            try:
                self.release()
            except Exception:
                self.log.exception(
                    f"Cleanup of Virtual Machine {self.vm_name} also failed"
                )
            raise

    def provision(self, cpu_cores: int, memory: str) -> None:
        """Provisions a VM in the namespace."""
        if not self.mac_address:
            raise RuntimeError(
                f"OpenShift Multus network '{self.udn_name}' requires paddles "
                f"node '{self.shortname}' to have a mac_address. Register a "
                f"MAC in paddles (lab DHCP/DNS map MAC→hostname→IP)."
            )

        user_data, network_data = self._get_user_data()
        if not user_data:
            raise RuntimeError("Failed to get user data")

        manifest = get_vm_manifest(
            namespace=self.namespace,
            vm_name=self.vm_name,
            cloud_init_user_data=user_data,
            cpu_cores=cpu_cores,
            memory=memory,
            datasource=get_datasource_name(self.os_type, self.os_version),
            datasource_namespace=get_datasource_namespace(),
            root_storage_size=get_root_storage_size(),
            root_storage_class=get_root_storage_class(),
            data_storage_class=get_data_storage_class(),
            udn_name=self.udn_name,
            mac_address=self.mac_address,
            udn_binding=self.udn_binding,
            extra_volumes=get_volumes(),
            cloud_init_network_data=network_data,
        )
        self.log.debug("Manifest: %s", manifest)
        client = _kubernetes_client()
        try:
            response = self.objects_api.create_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=self.namespace,
                plural=self.plural,
                body=manifest,
            )
            self.log.debug("Response: %s", response)
        except client.ApiException as e:
            self.log.error(
                f"Failed to provision Virtual Machine {self.vm_name} "
                f"in namespace {self.namespace} due to error:\n{str(e)}"
            )
            raise

    def release(self) -> None:
        """Release the OpenShift Virtual Machine"""
        self.delete()
        self._wait_for_deleted()

    def delete(self) -> bool:
        """Deletes a VM in the namespace.

        Uses Foreground cascading deletion so owned DataVolumes are removed
        before the VirtualMachine object itself disappears. Callers that will
        recreate the VM must still call ``_wait_for_deleted`` to cover leftovers
        from older Background deletes.

        :returns: True if a delete was issued, False if the VM was already absent
        """
        client = _kubernetes_client()
        try:
            self.log.info(
                f"Deleting Virtual Machine {self.vm_name} "
                f"in namespace {self.namespace} ..."
            )
            self.objects_api.delete_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=self.namespace,
                plural=self.plural,
                name=self.vm_name,
                propagation_policy="Foreground",
            )
            self.log.info(
                f"Successfully deleted Virtual Machine {self.vm_name} "
                f"in namespace {self.namespace} ..."
            )
            return True
        except client.ApiException as e:
            if e.status == 404:
                self.log.info(
                    f"Virtual Machine {self.vm_name} not found; "
                    f"already deleted"
                )
                return False
            self.log.error(
                f"Failed to delete Virtual Machine {self.vm_name} "
                f"in namespace {self.namespace} due to error:\n{str(e)}"
            )
            raise

    def _owned_storage_names(self) -> List[str]:
        """Return DataVolume/PVC names that belong to this VM."""
        names = [f"{self.vm_name}-rootdisk"]
        try:
            result = self.objects_api.list_namespaced_custom_object(
                group="cdi.kubevirt.io",
                version="v1beta1",
                namespace=self.namespace,
                plural="datavolumes",
            )
            for item in result.get("items") or []:
                name = (item.get("metadata") or {}).get("name") or ""
                if name.startswith(f"{self.vm_name}-vol-"):
                    names.append(name)
        except Exception as exc:
            # CRD may be absent in unit tests; PVC checks still cover recreate.
            self.log.debug(
                f"Could not list DataVolumes while checking leftovers for "
                f"{self.vm_name}: {exc}"
            )
        try:
            pvc_list = self.core_api.list_namespaced_persistent_volume_claim(
                namespace=self.namespace
            )
            for item in getattr(pvc_list, "items", None) or []:
                name = getattr(getattr(item, "metadata", None), "name", None)
                if not name:
                    continue
                if name.startswith(f"{self.vm_name}-vol-") and name not in names:
                    names.append(name)
        except Exception as exc:
            self.log.debug(
                f"Could not list PVCs while checking leftovers for "
                f"{self.vm_name}: {exc}"
            )
        return names

    def _resource_exists(
        self, *, group: Optional[str], version: Optional[str],
        plural: str, name: str, core: bool = False,
    ) -> bool:
        """Return True if a namespaced object still exists."""
        client = _kubernetes_client()
        try:
            if core:
                self.core_api.read_namespaced_persistent_volume_claim(
                    name=name, namespace=self.namespace
                )
            else:
                self.objects_api.get_namespaced_custom_object(
                    group=group,
                    version=version,
                    namespace=self.namespace,
                    plural=plural,
                    name=name,
                )
            return True
        except client.ApiException as e:
            if e.status == 404:
                return False
            raise

    def _lingering_storage(self) -> List[str]:
        """Return owned DataVolume/PVC names that still exist."""
        leftovers: List[str] = []
        for name in self._owned_storage_names():
            if self._resource_exists(
                group="cdi.kubevirt.io",
                version="v1beta1",
                plural="datavolumes",
                name=name,
            ):
                leftovers.append(f"datavolume/{name}")
            if self._resource_exists(
                group=None, version=None, plural="persistentvolumeclaims",
                name=name, core=True,
            ):
                leftovers.append(f"pvc/{name}")
        return leftovers

    def _wait_for_deleted(
        self, timeout: Optional[int] = None, interval: int = 5,
    ) -> None:
        """Wait until the VM and its DataVolumes/PVCs are fully gone.

        Foreground VM deletion should remove owned DataVolumes before the VM
        404s, but leftovers from older Background deletes can still block
        recreate of ``<vm>-rootdisk`` / ``<vm>-vol-N``.
        """
        if timeout is None:
            timeout = get_timeout()
        self.log.info(
            f"Waiting for Virtual Machine {self.vm_name} and owned storage "
            f"to be fully deleted within {timeout}s ..."
        )
        try:
            with safe_while(sleep=interval, timeout=timeout) as proceed:
                while proceed():
                    vm_present = self._resource_exists(
                        group=self.group,
                        version=self.version,
                        plural=self.plural,
                        name=self.vm_name,
                    )
                    leftovers = self._lingering_storage()
                    if not vm_present and not leftovers:
                        self.log.info(
                            f"Virtual Machine {self.vm_name} and owned storage "
                            f"are deleted"
                        )
                        return
                    if vm_present:
                        self.log.debug(
                            f"Virtual Machine {self.vm_name} still present, "
                            f"waiting {interval}s ..."
                        )
                    if leftovers:
                        self.log.debug(
                            f"Owned storage still present for {self.vm_name}: "
                            f"{', '.join(leftovers)}; waiting {interval}s ..."
                        )
        except MaxWhileTries as exc:
            raise RuntimeError(
                f"Virtual Machine {self.vm_name} (or owned DataVolumes/PVCs) "
                f"still present after {timeout}s of polling"
            ) from exc

    def _get_user_data(self) -> Tuple[Optional[str], Optional[str]]:
        """Load OS-specific OCP cloud-init user-data and network-data.

        Templates are cloud-init only. Extra disks and DataSource names come
        from ``openshift.volumes`` / ``openshift.datasources``.

        :returns: (cloud-init user-data, network-data)
        """
        user_data_template = _openshift_conf().get("user_data")
        if not user_data_template:
            return None, None

        user_data_path = user_data_template.format(
            os_type=self.os_type, os_version=self.os_version
        )
        if not os.path.exists(user_data_path):
            raise RuntimeError(
                f"OpenShift user_data template not found: {user_data_path}"
            )

        return parse_user_data_file(
            user_data_path,
            ssh_authorized_keys=get_ssh_authorized_keys(),
        )

    def _iface_ips(self, iface: dict) -> List[str]:
        ips: List[str] = []
        ip = iface.get("ipAddress")
        if ip:
            ips.append(ip)
        for candidate in iface.get("ipAddresses") or []:
            if candidate and candidate not in ips:
                ips.append(candidate)
        return ips

    def _get_ip_from_vmi(self, vmi: Optional[dict]) -> Optional[str]:
        """Return the Multus guest IP from a VMI status.

        Only the configured Multus interface (``udn_name``) is accepted.
        """
        if not vmi or not self.udn_name:
            return None
        status = vmi.get("status") or {}
        interfaces = status.get("interfaces") or []
        for iface in interfaces:
            if iface.get("name") == self.udn_name:
                ips = self._iface_ips(iface)
                if ips:
                    return ips[0]
        return None

    def _wait_for_ip_address(
        self, timeout: Optional[int] = None, interval: int = 5,
    ) -> str:
        """Poll until the UDN IP address is available or timeout expires.

        :param timeout: The maximum time to wait for the IP address
        :param interval: The time to wait between polling attempts

        :returns: The IP address of the VM
        :raises: RuntimeError if the VM does not have an IP address
            within the timeout period
        """
        if timeout is None:
            timeout = get_timeout()
        self.log.info(
            f"Waiting for {self.udn_name} IP address for Virtual Machine "
            f"{self.vm_name} for {timeout} seconds ..."
        )
        client = _kubernetes_client()
        try:
            with safe_while(sleep=interval, timeout=timeout) as proceed:
                while proceed():
                    self.log.debug(
                        f"Polling for Virtual Machine {self.vm_name} "
                        f"IP address ..."
                    )
                    try:
                        vmi = self.objects_api.get_namespaced_custom_object(
                            group=self.group,
                            version=self.version,
                            namespace=self.namespace,
                            plural=self.vmi_plural,
                            name=self.vm_name,
                        )
                    except client.ApiException as e:
                        if e.status != 404:
                            self.log.error(
                                f"Failed to get IP address for Virtual Machine "
                                f"{self.vm_name} due to error:\n{str(e)}"
                            )
                            raise
                        vmi = None

                    ip = self._get_ip_from_vmi(vmi)
                    if not ip:
                        self.log.debug(
                            f"Virtual Machine {self.vm_name} has no "
                            f"{self.udn_name} IP yet, waiting for "
                            f"{interval} seconds ..."
                        )
                        continue

                    self.log.info(
                        f"Virtual Machine {self.vm_name} has IP address: {ip}"
                    )
                    return ip
        except MaxWhileTries as exc:
            raise RuntimeError(
                f"Virtual Machine {self.vm_name} has no {self.udn_name} IP "
                f"after {timeout} seconds of polling"
            ) from exc

    def _wait_for_ready(self, timeout: Optional[int] = None) -> None:
        """Wait until SSH works, then verify the installed OS.

        Every reimage creates new host keys; remove stale known_hosts entries
        so BadHostKeyException does not burn the whole timeout.
        """
        if timeout is None:
            timeout = get_timeout()
        self.log.info(
            f"Waiting for SSH on {self.name} for up to {timeout}s ..."
        )
        try:
            with safe_while(sleep=6, timeout=timeout) as proceed:
                while proceed():
                    try:
                        self.remote.connect()
                        break
                    except BadHostKeyException as e:
                        self.log.warning(
                            f"{e}; removing stale known_hosts entry "
                            f"for {self.name}"
                        )
                        misc.ssh_keygen_remove(self.name)
                    except (
                        socket.error,
                        SSHException,
                        NoValidConnectionsError,
                        MaxWhileTries,
                        EOFError,
                    ) as e:
                        self.log.warning(e)
        except MaxWhileTries as exc:
            raise RuntimeError(
                f"SSH to {self.name} did not become ready within {timeout}s"
            ) from exc
        self._verify_installed_os()
        self.log.info("Node is ready")

    def _verify_installed_os(self) -> None:
        """Verify that the installed OS matches the expected OS."""
        wanted_os = OS(name=self.os_type, version=self.os_version)
        if self.remote.os != wanted_os:
            raise RuntimeError(
                f"Expected {self.remote.shortname}'s OS to be '{wanted_os}' "
                f"but found '{self.remote.os}'"
            )

    def _wait_for_status(
        self,
        status: str = "Running",
        timeout: Optional[int] = None,
        interval: int = 5,
    ) -> None:
        """Poll until the VM reaches the desired status or timeout expires.

        :param status: The desired status to wait for
        :param timeout: The maximum time to wait for the status
        :param interval: The time to wait between status checks

        :raises: RuntimeError if the VM does not reach the desired status
            within the timeout period
        """
        if timeout is None:
            timeout = get_timeout()
        self.log.info(
            f"Waiting for Virtual Machine {self.vm_name} to reach status "
            f"{status} within {timeout}s ..."
        )
        client = _kubernetes_client()
        _status = "Unknown"
        try:
            with safe_while(sleep=interval, timeout=timeout) as proceed:
                while proceed():
                    self.log.debug(
                        f"Polling for Virtual Machine {self.vm_name} status ..."
                    )
                    try:
                        vm = self.objects_api.get_namespaced_custom_object(
                            group=self.group,
                            version=self.version,
                            namespace=self.namespace,
                            plural=self.plural,
                            name=self.vm_name,
                        )
                    except client.ApiException as e:
                        if e.status == 404 and status.lower() == "deleted":
                            self.log.info(
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
                        self.log.info(
                            f"Virtual Machine {self.vm_name} reached status "
                            f"{_status}"
                        )
                        return

                    self.log.debug(
                        f"Virtual Machine {self.vm_name} is in status {_status},"
                        f"waiting {interval}s to reach status {status} ..."
                    )
        except MaxWhileTries as exc:
            raise RuntimeError(
                f"Virtual Machine {self.vm_name} is in status '{_status}' "
                f"after {timeout}s of polling, expected status is '{status}'"
            ) from exc
