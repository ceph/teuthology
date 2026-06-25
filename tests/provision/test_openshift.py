from teuthology.provision import openshift


class TestOpenShiftHelpers:
    def test_resolve_datasource_centos_stream(self):
        assert openshift._resolve_datasource_name('centos', '9.stream') == \
            'centos-stream9'
        assert openshift._resolve_datasource_name('centos', '10') == \
            'centos-stream10'
        assert openshift._resolve_datasource_name('centos', 'stream10') is None

    def test_vm_manifest_masquerade_only(self):
        manifest = openshift.get_vm_manifest(
            namespace='ns',
            vm_name='target-00',
            cloud_init_user_data='#cloud-config\n',
            cpu_cores=2,
            memory='2Gi',
            datasource='centos-stream9',
            datasource_namespace='openshift-virtualization-os-images',
            storage_size='30Gi',
        )
        assert manifest['metadata']['name'] == 'target-00'
        assert manifest['spec']['template']['spec']['domain']['devices'][
            'interfaces'] == [{'name': 'default', 'masquerade': {}}]
        assert manifest['spec']['template']['spec']['networks'] == [
            {'name': 'default', 'pod': {}},
        ]
        assert manifest['spec']['dataVolumeTemplates'][0]['metadata'][
            'name'] == 'target-00-rootdisk'

    def test_vm_manifest_with_udn(self):
        manifest = openshift.get_vm_manifest(
            namespace='ns',
            vm_name='target-00',
            cloud_init_user_data='#cloud-config\n',
            cpu_cores=2,
            memory='2Gi',
            datasource='centos-stream9',
            datasource_namespace='openshift-virtualization-os-images',
            storage_size='30Gi',
            udn_name='teuthology-net',
            mac_address='52:54:00:00:00:00',
            udn_binding='l2bridge',
        )
        ifaces = manifest['spec']['template']['spec']['domain']['devices'][
            'interfaces']
        networks = manifest['spec']['template']['spec']['networks']
        assert ifaces[0] == {'name': 'default', 'masquerade': {}}
        assert ifaces[1] == {
            'name': 'teuthology-net',
            'macAddress': '52:54:00:00:00:00',
            'binding': {'name': 'l2bridge'},
        }
        assert networks[1] == {
            'name': 'teuthology-net',
            'multus': {'networkName': 'teuthology-net'},
        }
