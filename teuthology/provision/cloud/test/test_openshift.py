import pytest
from unittest.mock import Mock, MagicMock, patch

from teuthology.provision.cloud import openshift


class TestOpenShiftProvider:
    def setup_method(self):
        self.provider_conf = {
            'driver': 'openshift',
            'namespace': 'teuthology-test',
            'kubeconfig': '/path/to/kubeconfig',
            'context': 'test-context',
            'ssh_service_type': 'NodePort',
        }
    
    @patch('teuthology.provision.cloud.openshift.k8s_config')
    @patch('teuthology.provision.cloud.openshift.client')
    def test_init(self, mock_client, mock_k8s_config):
        """Test OpenShiftProvider initialization"""
        mock_core_api = Mock()
        mock_custom_api = Mock()
        mock_client.CoreV1Api.return_value = mock_core_api
        mock_client.CustomObjectsApi.return_value = mock_custom_api
        
        provider = openshift.OpenShiftProvider(
            name='test-provider',
            conf=self.provider_conf
        )
        
        assert provider.name == 'test-provider'
        assert provider.namespace == 'teuthology-test'
        mock_k8s_config.load_kube_config.assert_called_once_with(
            config_file='/path/to/kubeconfig',
            context='test-context'
        )
    
    @patch('teuthology.provision.cloud.openshift.k8s_config')
    @patch('teuthology.provision.cloud.openshift.client')
    def test_available_images(self, mock_client, mock_k8s_config):
        """Test listing available images"""
        mock_custom_api = Mock()
        mock_client.CustomObjectsApi.return_value = mock_custom_api
        
        # Mock DataVolumes response
        mock_custom_api.list_namespaced_custom_object.return_value = {
            'items': [
                {
                    'metadata': {
                        'name': 'ubuntu-22-04',
                        'namespace': 'teuthology-test'
                    }
                },
                {
                    'metadata': {
                        'name': 'centos-9',
                        'namespace': 'teuthology-test'
                    }
                }
            ]
        }
        
        provider = openshift.OpenShiftProvider(
            name='test-provider',
            conf=self.provider_conf
        )
        
        images = provider.available_images
        assert len(images) == 2
        assert images[0]['name'] == 'ubuntu-22-04'
        assert images[1]['name'] == 'centos-9'
    
    @patch('teuthology.provision.cloud.openshift.k8s_config')
    @patch('teuthology.provision.cloud.openshift.client')
    def test_ssh_service_type(self, mock_client, mock_k8s_config):
        """Test SSH service type configuration"""
        provider = openshift.OpenShiftProvider(
            name='test-provider',
            conf=self.provider_conf
        )
        
        assert provider.ssh_service_type == 'NodePort'


class TestOpenShiftProvisioner:
    def setup_method(self):
        self.provider_conf = {
            'driver': 'openshift',
            'namespace': 'teuthology-test',
            'kubeconfig': '/path/to/kubeconfig',
            'ssh_service_type': 'NodePort',
        }
        
        self.instance_conf = {
            'openshift': {
                'machine': {
                    'memory': '16Gi',
                    'cpus': 4,
                    'disk': '40Gi',
                }
            }
        }
    
    @patch('teuthology.provision.cloud.openshift.k8s_config')
    @patch('teuthology.provision.cloud.openshift.client')
    def test_init(self, mock_client, mock_k8s_config):
        """Test OpenShiftProvisioner initialization"""
        provider = openshift.OpenShiftProvider(
            name='test-provider',
            conf=self.provider_conf
        )
        
        provisioner = openshift.OpenShiftProvisioner(
            provider=provider,
            name='test-node-001',
            os_type='ubuntu',
            os_version='22.04',
            conf=self.instance_conf,
            user='ubuntu'
        )
        
        assert provisioner.name == 'test-node-001'
        assert provisioner.os_type == 'ubuntu'
        assert provisioner.os_version == '22.04'
        assert provisioner.user == 'ubuntu'
        assert provisioner.conf['machine']['memory'] == '16Gi'
        assert provisioner.conf['machine']['cpus'] == 4
    
    @patch('teuthology.provision.cloud.openshift.k8s_config')
    @patch('teuthology.provision.cloud.openshift.client')
    @patch('teuthology.provision.cloud.util.get_user_ssh_pubkey')
    def test_userdata_generation(self, mock_ssh_key, mock_client, mock_k8s_config):
        """Test cloud-init userdata generation"""
        mock_ssh_key.return_value = 'ssh-rsa AAAAB3NzaC1yc2E...'
        
        provider = openshift.OpenShiftProvider(
            name='test-provider',
            conf=self.provider_conf
        )
        
        provisioner = openshift.OpenShiftProvisioner(
            provider=provider,
            name='test-node-001',
            os_type='ubuntu',
            os_version='22.04',
            user='ubuntu'
        )
        
        userdata = provisioner.userdata
        
        assert '#cloud-config' in userdata
        assert 'packages:' in userdata
        assert 'git' in userdata
        assert 'ssh_authorized_keys:' in userdata
        assert 'ssh-rsa AAAAB3NzaC1yc2E...' in userdata
    
    @patch('teuthology.provision.cloud.openshift.k8s_config')
    @patch('teuthology.provision.cloud.openshift.client')
    def test_build_vm_spec(self, mock_client, mock_k8s_config):
        """Test VirtualMachine spec building"""
        provider = openshift.OpenShiftProvider(
            name='test-provider',
            conf=self.provider_conf
        )
        
        provisioner = openshift.OpenShiftProvisioner(
            provider=provider,
            name='test-node-001',
            os_type='ubuntu',
            os_version='22.04',
            conf=self.instance_conf,
            user='ubuntu'
        )
        
        # Mock the image
        provisioner._image = {
            'name': 'ubuntu-22-04',
            'namespace': 'teuthology-test',
            'type': 'datavolume'
        }
        
        userdata = "#cloud-config\npackages: [git]"
        vm_spec = provisioner._build_vm_spec(userdata)
        
        assert vm_spec['kind'] == 'VirtualMachine'
        assert vm_spec['metadata']['name'] == 'test-node-001'
        assert vm_spec['spec']['template']['spec']['domain']['resources']['requests']['memory'] == '16Gi'
        assert vm_spec['spec']['template']['spec']['domain']['resources']['requests']['cpu'] == '4'
        assert len(vm_spec['spec']['dataVolumeTemplates']) == 1
        assert vm_spec['spec']['dataVolumeTemplates'][0]['metadata']['name'] == 'test-node-001-root'
    
    @patch('teuthology.provision.cloud.openshift.k8s_config')
    @patch('teuthology.provision.cloud.openshift.client')
    def test_image_selection(self, mock_client, mock_k8s_config):
        """Test image selection based on OS type and version"""
        mock_custom_api = Mock()
        mock_client.CustomObjectsApi.return_value = mock_custom_api
        
        # Mock available images
        mock_custom_api.list_namespaced_custom_object.return_value = {
            'items': [
                {
                    'metadata': {
                        'name': 'ubuntu-22-04-image',
                        'namespace': 'teuthology-test'
                    }
                },
                {
                    'metadata': {
                        'name': 'centos-9-image',
                        'namespace': 'teuthology-test'
                    }
                }
            ]
        }
        
        provider = openshift.OpenShiftProvider(
            name='test-provider',
            conf=self.provider_conf
        )
        
        provisioner = openshift.OpenShiftProvisioner(
            provider=provider,
            name='test-node-001',
            os_type='ubuntu',
            os_version='22.04',
            user='ubuntu'
        )
        
        image = provisioner.image
        assert 'ubuntu' in image['name'].lower()
        assert '22' in image['name']
    
    @patch('teuthology.provision.cloud.openshift.k8s_config')
    @patch('teuthology.provision.cloud.openshift.client')
    def test_encode_userdata(self, mock_client, mock_k8s_config):
        """Test base64 encoding of userdata"""
        provider = openshift.OpenShiftProvider(
            name='test-provider',
            conf=self.provider_conf
        )
        
        provisioner = openshift.OpenShiftProvisioner(
            provider=provider,
            name='test-node-001',
            os_type='ubuntu',
            os_version='22.04',
            user='ubuntu'
        )
        
        userdata = "#cloud-config\npackages: [git]"
        encoded = provisioner._encode_userdata(userdata)
        
        # Verify it's base64 encoded
        import base64
        decoded = base64.b64decode(encoded).decode('utf-8')
        assert decoded == userdata






