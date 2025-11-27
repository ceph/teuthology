import logging
import re
import time
import yaml
from copy import deepcopy

from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException

from paramiko import AuthenticationException
from paramiko.ssh_exception import NoValidConnectionsError

from teuthology.config import config
from teuthology.contextutil import safe_while
from teuthology.provision.cloud import base
from teuthology.provision.cloud import util

log = logging.getLogger(__name__)


RETRY_EXCEPTIONS = (ApiException,)


def retry(function, *args, **kwargs):
    """
    Call a function (returning its results), retrying if any of the exceptions
    in RETRY_EXCEPTIONS are raised
    """
    with safe_while(sleep=1, tries=24, increment=1) as proceed:
        tries = 0
        while proceed():
            tries += 1
            try:
                result = function(*args, **kwargs)
                if tries > 1:
                    log.debug(
                        "'%s' succeeded after %s tries",
                        function.__name__,
                        tries,
                    )
                return result
            except RETRY_EXCEPTIONS as e:
                log.debug(f"Retry attempt {tries} failed: {e}")
                if tries >= 24:
                    raise


class OpenShiftProvider(base.Provider):
    """
    Provider for OpenShift Virtualization (KubeVirt) VMs
    """
    
    def __init__(self, name, conf):
        super(OpenShiftProvider, self).__init__(name, conf)
        self._init_kubernetes_client()
    
    def _init_kubernetes_client(self):
        """Initialize Kubernetes client for OpenShift"""
        kubeconfig = self.conf.get('kubeconfig')
        context = self.conf.get('context')
        
        if kubeconfig:
            k8s_config.load_kube_config(config_file=kubeconfig, context=context)
        else:
            # Try in-cluster config if no kubeconfig provided
            try:
                k8s_config.load_incluster_config()
            except k8s_config.ConfigException:
                # Fall back to default kubeconfig
                k8s_config.load_kube_config(context=context)
        
        self._core_api = client.CoreV1Api()
        self._custom_api = client.CustomObjectsApi()
        self._namespace = self.conf.get('namespace', 'default')
    
    @property
    def core_api(self):
        return self._core_api
    
    @property
    def custom_api(self):
        return self._custom_api
    
    @property
    def namespace(self):
        return self._namespace
    
    @property
    def driver(self):
        """For compatibility with base class"""
        return self
    
    @property
    def driver_name(self):
        return 'openshift'
    
    @property
    def available_images(self):
        """List available VM images (DataVolumes or PVCs)"""
        if not hasattr(self, '_available_images'):
            exclude_image = self.conf.get('exclude_image', [])
            if exclude_image and not isinstance(exclude_image, list):
                exclude_image = [exclude_image]
            exclude_re = [re.compile(x) for x in exclude_image]
            
            # Get DataVolumes that can be used as VM images
            try:
                dvs = self.custom_api.list_namespaced_custom_object(
                    group="cdi.kubevirt.io",
                    version="v1beta1",
                    namespace=self.namespace,
                    plural="datavolumes"
                )
                
                images = []
                for dv in dvs.get('items', []):
                    name = dv['metadata']['name']
                    if not any(x.match(name) for x in exclude_re):
                        images.append({
                            'name': name,
                            'namespace': dv['metadata']['namespace'],
                            'type': 'datavolume'
                        })
                
                self._available_images = images
            except ApiException as e:
                log.warning(f"Unable to list DataVolumes: {e}")
                self._available_images = []
        
        return self._available_images
    
    @property
    def available_instance_types(self):
        """List available VirtualMachineInstancetypes"""
        if not hasattr(self, '_available_instance_types'):
            allow_types = self.conf.get('allow_instance_types', '.*')
            if not isinstance(allow_types, list):
                allow_types = [allow_types]
            allow_re = [re.compile(x) for x in allow_types]
            
            exclude_types = self.conf.get('exclude_instance_types', [])
            if not isinstance(exclude_types, list):
                exclude_types = [exclude_types]
            exclude_re = [re.compile(x) for x in exclude_types]
            
            try:
                instance_types = self.custom_api.list_cluster_custom_object(
                    group="instancetype.kubevirt.io",
                    version="v1beta1",
                    plural="virtualmachineinstancetypes"
                )
                
                types = []
                for it in instance_types.get('items', []):
                    name = it['metadata']['name']
                    if (any(x.match(name) for x in allow_re) and
                        not any(x.match(name) for x in exclude_re)):
                        types.append({
                            'name': name,
                            'cpu': it['spec'].get('cpu', {}).get('guest', 1),
                            'memory': it['spec'].get('memory', {}).get('guest', '2Gi'),
                        })
                
                self._available_instance_types = types
            except ApiException as e:
                log.warning(f"Unable to list VirtualMachineInstancetypes: {e}")
                self._available_instance_types = []
        
        return self._available_instance_types
    
    @property
    def default_userdata(self):
        if not hasattr(self, '_default_userdata'):
            self._default_userdata = self.conf.get('userdata', dict())
        return self._default_userdata
    
    @property
    def ssh_service_type(self):
        """Type of Kubernetes service to expose SSH (NodePort, LoadBalancer, ClusterIP)"""
        return self.conf.get('ssh_service_type', 'NodePort')


class OpenShiftProvisioner(base.Provisioner):
    """
    Provisioner for OpenShift Virtualization (KubeVirt) VMs
    """
    _sentinel_path = '/.teuth_provisioned'
    
    defaults = dict(
        openshift=dict(
            machine=dict(
                memory='8Gi',
                cpus=2,
                disk='20Gi',
            ),
            volumes=dict(
                count=0,
                size='10Gi',
            ),
        )
    )
    
    def __init__(
        self,
        provider, name, os_type=None, os_version=None,
        conf=None,
        user='ubuntu',
    ):
        if isinstance(provider, str):
            from teuthology.provision import cloud
            provider = cloud.get_provider(provider)
        
        super(OpenShiftProvisioner, self).__init__(
            provider, name, os_type, os_version, conf=conf, user=user,
        )
        self._read_conf(conf)
    
    def _read_conf(self, conf=None):
        """
        Looks through the following in order:
        
            the 'conf' arg
            conf[DRIVER_NAME]
            teuthology.config.config.DRIVER_NAME
            self.defaults[DRIVER_NAME]
        
        It will use the highest value for each of the following: memory, CPU,
        disk, volume size and count
        
        The resulting configuration becomes the new instance configuration
        and is stored as self.conf
        
        :param conf: The instance configuration
        :return: None
        """
        driver_name = 'openshift'
        full_conf = conf or dict()
        driver_conf = full_conf.get(driver_name, dict())
        legacy_conf = getattr(config, driver_name, None) or dict()
        defaults = self.defaults.get(driver_name, dict())
        confs = list()
        for obj in (full_conf, driver_conf, legacy_conf, defaults):
            obj = deepcopy(obj)
            if isinstance(obj, list):
                confs.extend(obj)
            else:
                confs.append(obj)
        self.conf = util.combine_dicts(confs, lambda x, y: x > y)
    
    def _create(self):
        """Create a VirtualMachine in OpenShift"""
        userdata = self.userdata
        log.debug("Creating VM: %s", self)
        log.debug("Using userdata: %s", userdata)
        
        vm_spec = self._build_vm_spec(userdata)
        
        try:
            # Create the VirtualMachine
            vm = retry(
                self.provider.custom_api.create_namespaced_custom_object,
                group="kubevirt.io",
                version="v1",
                namespace=self.provider.namespace,
                plural="virtualmachines",
                body=vm_spec
            )
            log.debug("Created VM: %s", vm['metadata']['name'])
            
            # Start the VM
            self._start_vm()
            
            # Wait for VM to be ready
            self._wait_for_vm_running()
            
            # Create service for SSH access
            self._create_ssh_service()
            
            # Create additional volumes if needed
            if not self._create_volumes():
                self._destroy_volumes()
                return False
            
            # Get VM IP/hostname
            self.ip_address = self._get_vm_ip()
            log.info("VM IP address: %s", self.ip_address)
            
            # Wait for SSH to be ready
            time.sleep(20)
            self._wait_for_ready()
            
            return True
        except Exception as e:
            log.exception("Failed to create VM: %s", e)
            return False
    
    def _build_vm_spec(self, userdata):
        """Build VirtualMachine specification"""
        instance_type = self.instance_type
        
        vm_spec = {
            'apiVersion': 'kubevirt.io/v1',
            'kind': 'VirtualMachine',
            'metadata': {
                'name': self.name,
                'namespace': self.provider.namespace,
                'labels': {
                    'app': 'teuthology',
                    'teuthology-vm': self.name,
                }
            },
            'spec': {
                'running': False,  # We'll start it manually after creation
                'template': {
                    'metadata': {
                        'labels': {
                            'teuthology-vm': self.name,
                        }
                    },
                    'spec': {
                        'domain': {
                            'devices': {
                                'disks': [
                                    {
                                        'name': 'rootdisk',
                                        'disk': {
                                            'bus': 'virtio'
                                        }
                                    },
                                    {
                                        'name': 'cloudinitdisk',
                                        'disk': {
                                            'bus': 'virtio'
                                        }
                                    }
                                ],
                                'interfaces': [
                                    {
                                        'name': 'default',
                                        'masquerade': {}
                                    }
                                ]
                            },
                            'resources': {
                                'requests': {
                                    'memory': self.conf['machine']['memory'],
                                    'cpu': str(self.conf['machine']['cpus'])
                                }
                            }
                        },
                        'networks': [
                            {
                                'name': 'default',
                                'pod': {}
                            }
                        ],
                        'volumes': [
                            {
                                'name': 'rootdisk',
                                'dataVolume': {
                                    'name': f"{self.name}-root"
                                }
                            },
                            {
                                'name': 'cloudinitdisk',
                                'cloudInitNoCloud': {
                                    'userDataBase64': self._encode_userdata(userdata)
                                }
                            }
                        ]
                    }
                },
                'dataVolumeTemplates': [
                    {
                        'metadata': {
                            'name': f"{self.name}-root"
                        },
                        'spec': {
                            'pvc': {
                                'accessModes': ['ReadWriteOnce'],
                                'resources': {
                                    'requests': {
                                        'storage': self.conf['machine']['disk']
                                    }
                                }
                            },
                            'source': {
                                'pvc': {
                                    'name': self.image['name'],
                                    'namespace': self.image.get('namespace', self.provider.namespace)
                                }
                            }
                        }
                    }
                ]
            }
        }
        
        return vm_spec
    
    def _encode_userdata(self, userdata):
        """Base64 encode userdata"""
        import base64
        return base64.b64encode(userdata.encode('utf-8')).decode('utf-8')
    
    def _start_vm(self):
        """Start the VirtualMachine"""
        patch = {
            'spec': {
                'running': True
            }
        }
        retry(
            self.provider.custom_api.patch_namespaced_custom_object,
            group="kubevirt.io",
            version="v1",
            namespace=self.provider.namespace,
            plural="virtualmachines",
            name=self.name,
            body=patch
        )
        log.debug("Started VM: %s", self.name)
    
    def _wait_for_vm_running(self):
        """Wait for VirtualMachineInstance to be running"""
        with safe_while(sleep=5, tries=60) as proceed:
            while proceed():
                try:
                    vmi = self.provider.custom_api.get_namespaced_custom_object(
                        group="kubevirt.io",
                        version="v1",
                        namespace=self.provider.namespace,
                        plural="virtualmachineinstances",
                        name=self.name
                    )
                    phase = vmi.get('status', {}).get('phase')
                    if phase == 'Running':
                        log.info("VM is running: %s", self.name)
                        return True
                    log.debug("VM phase: %s", phase)
                except ApiException:
                    pass
        raise RuntimeError(f"VM {self.name} did not reach Running state")
    
    def _create_ssh_service(self):
        """Create a Kubernetes Service to expose SSH"""
        service_spec = {
            'apiVersion': 'v1',
            'kind': 'Service',
            'metadata': {
                'name': f"{self.name}-ssh",
                'namespace': self.provider.namespace,
                'labels': {
                    'app': 'teuthology',
                    'teuthology-vm': self.name,
                }
            },
            'spec': {
                'type': self.provider.ssh_service_type,
                'selector': {
                    'teuthology-vm': self.name,
                },
                'ports': [
                    {
                        'name': 'ssh',
                        'protocol': 'TCP',
                        'port': 22,
                        'targetPort': 22
                    }
                ]
            }
        }
        
        try:
            retry(
                self.provider.core_api.create_namespaced_service,
                namespace=self.provider.namespace,
                body=service_spec
            )
            log.debug("Created SSH service for VM: %s", self.name)
        except ApiException as e:
            if e.status != 409:  # Ignore if already exists
                raise
    
    def _get_vm_ip(self):
        """Get the IP address to connect to the VM"""
        service_type = self.provider.ssh_service_type
        
        if service_type == 'LoadBalancer':
            # Wait for LoadBalancer IP
            with safe_while(sleep=5, tries=30) as proceed:
                while proceed():
                    svc = self.provider.core_api.read_namespaced_service(
                        name=f"{self.name}-ssh",
                        namespace=self.provider.namespace
                    )
                    if svc.status.load_balancer.ingress:
                        return svc.status.load_balancer.ingress[0].ip or \
                               svc.status.load_balancer.ingress[0].hostname
        elif service_type == 'NodePort':
            # Get node IP and NodePort
            nodes = self.provider.core_api.list_node()
            if not nodes.items:
                raise RuntimeError(f"No nodes found in cluster for VM {self.name}")
            
            node_ip = None
            # Prefer ExternalIP, fallback to InternalIP
            for address in nodes.items[0].status.addresses:
                if address.type == 'ExternalIP':
                    node_ip = address.address
                    break
                elif address.type == 'InternalIP' and node_ip is None:
                    node_ip = address.address
            
            if not node_ip:
                raise RuntimeError(f"Could not determine node IP for VM {self.name}")
            
            svc = self.provider.core_api.read_namespaced_service(
                name=f"{self.name}-ssh",
                namespace=self.provider.namespace
            )
            node_port = svc.spec.ports[0].node_port
            return f"{node_ip}:{node_port}"
        else:
            # ClusterIP - get pod IP directly
            vmi = self.provider.custom_api.get_namespaced_custom_object(
                group="kubevirt.io",
                version="v1",
                namespace=self.provider.namespace,
                plural="virtualmachineinstances",
                name=self.name
            )
            interfaces = vmi.get('status', {}).get('interfaces', [])
            if interfaces:
                return interfaces[0].get('ipAddress')
        
        raise RuntimeError(f"Could not determine IP for VM {self.name}")
    
    def _create_volumes(self):
        """Create additional PVCs for the VM"""
        vol_count = self.conf['volumes']['count']
        if vol_count == 0:
            return True
        
        vol_size = self.conf['volumes']['size']
        
        try:
            for i in range(vol_count):
                pvc_name = f"{self.name}-vol-{i}"
                pvc_spec = {
                    'apiVersion': 'v1',
                    'kind': 'PersistentVolumeClaim',
                    'metadata': {
                        'name': pvc_name,
                        'namespace': self.provider.namespace,
                        'labels': {
                            'teuthology-vm': self.name,
                        }
                    },
                    'spec': {
                        'accessModes': ['ReadWriteOnce'],
                        'resources': {
                            'requests': {
                                'storage': vol_size
                            }
                        }
                    }
                }
                
                retry(
                    self.provider.core_api.create_namespaced_persistent_volume_claim,
                    namespace=self.provider.namespace,
                    body=pvc_spec
                )
                log.info("Created volume %s", pvc_name)
                
                # Attach volume to VM (requires VM restart)
                # This is a simplified approach - in production you might want hotplug
                
        except Exception:
            log.exception("Failed to create volumes!")
            return False
        return True
    
    def _destroy_volumes(self):
        """Destroy additional PVCs"""
        try:
            pvcs = self.provider.core_api.list_namespaced_persistent_volume_claim(
                namespace=self.provider.namespace,
                label_selector=f"teuthology-vm={self.name}"
            )
            
            for pvc in pvcs.items:
                if pvc.metadata.name.startswith(f"{self.name}-vol-"):
                    try:
                        retry(
                            self.provider.core_api.delete_namespaced_persistent_volume_claim,
                            name=pvc.metadata.name,
                            namespace=self.provider.namespace
                        )
                        log.info("Deleted volume %s", pvc.metadata.name)
                    except Exception:
                        log.exception("Could not delete volume %s", pvc.metadata.name)
        except Exception:
            log.exception("Error listing volumes")
    
    def _wait_for_ready(self):
        """Wait for SSH to be ready"""
        import socket
        with safe_while(sleep=6, tries=20) as proceed:
            while proceed():
                try:
                    self.remote.connect()
                    break
                except (
                    socket.error,
                    NoValidConnectionsError,
                    AuthenticationException,
                ):
                    pass
        
        cmd = "while [ ! -e '%s' ]; do sleep 5; done" % self._sentinel_path
        self.remote.run(args=cmd, timeout=600)
        log.info("VM is ready: %s", self.name)
    
    @property
    def image(self):
        """Find the appropriate image for the OS type and version"""
        if hasattr(self, '_image'):
            return self._image
        
        os_specs = [
            '{os_type}-{os_version}',
            '{os_type}{os_version}',
        ]
        
        for spec in os_specs:
            pattern = spec.format(
                os_type=self.os_type,
                os_version=self.os_version,
            )
            matches = [img for img in self.provider.available_images
                       if pattern.lower() in img['name'].lower()]
            if matches:
                self._image = matches[0]
                return self._image
        
        # If no match found, check config for explicit image
        explicit_image = self.conf.get('image_name')
        if explicit_image:
            self._image = {
                'name': explicit_image,
                'namespace': self.provider.namespace,
                'type': 'pvc'
            }
            return self._image
        
        raise RuntimeError(
            f"Could not find an image for {self.os_type} {self.os_version}"
        )
    
    @property
    def instance_type(self):
        """Get the instance type based on requirements"""
        if hasattr(self, '_instance_type'):
            return self._instance_type
        
        # For now, return None to use embedded resources
        # In future, could select from available instance types
        return None
    
    @property
    def userdata(self):
        """Generate cloud-init userdata"""
        spec = f"{self.os_type}-{self.os_version}"
        base_config = dict(
            packages=[
                'git',
                'wget',
                'python3',
                'ntp',
            ],
        )
        
        runcmd = [
            # Remove the user's password so that console logins are possible
            ['passwd', '-d', self.user],
            ['touch', self._sentinel_path]
        ]
        
        if spec in self.provider.default_userdata:
            base_config = deepcopy(
                self.provider.default_userdata.get(spec, dict())
            )
        
        base_config.update(user=self.user)
        if 'manage_etc_hosts' not in base_config:
            base_config.update(
                manage_etc_hosts=True,
                hostname=self.hostname,
            )
        
        base_config['runcmd'] = base_config.get('runcmd', list())
        base_config['runcmd'].extend(runcmd)
        
        ssh_pubkey = util.get_user_ssh_pubkey()
        if ssh_pubkey:
            authorized_keys = base_config.get('ssh_authorized_keys', list())
            authorized_keys.append(ssh_pubkey)
            base_config['ssh_authorized_keys'] = authorized_keys
        
        user_str = "#cloud-config\n" + yaml.safe_dump(base_config)
        return user_str
    
    def _destroy(self):
        """Destroy the VirtualMachine and associated resources"""
        try:
            # Destroy volumes
            self._destroy_volumes()
            
            # Delete SSH service
            try:
                self.provider.core_api.delete_namespaced_service(
                    name=f"{self.name}-ssh",
                    namespace=self.provider.namespace
                )
                log.info("Deleted SSH service for %s", self.name)
            except ApiException as e:
                if e.status != 404:
                    log.warning("Could not delete SSH service: %s", e)
            
            # Delete VirtualMachine
            try:
                self.provider.custom_api.delete_namespaced_custom_object(
                    group="kubevirt.io",
                    version="v1",
                    namespace=self.provider.namespace,
                    plural="virtualmachines",
                    name=self.name
                )
                log.info("Deleted VM: %s", self.name)
                return True
            except ApiException as e:
                if e.status == 404:
                    log.warning("VM %s not found", self.name)
                    return True
                raise
        except Exception:
            log.exception("Failed to destroy VM %s", self.name)
            return False


