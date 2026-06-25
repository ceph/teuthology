from pathlib import Path

from teuthology.provision import openshift

USER_DATA_DIR = Path(__file__).resolve().parents[2] / 'teuthology' / 'ocp' / 'user_data'


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
            root_storage_size='30Gi',
        )
        assert manifest['metadata']['name'] == 'target-00'
        assert manifest['spec']['template']['spec']['domain']['devices'][
            'interfaces'] == [{'name': 'default', 'masquerade': {}}]
        assert manifest['spec']['template']['spec']['networks'] == [
            {'name': 'default', 'pod': {}},
        ]
        assert manifest['spec']['dataVolumeTemplates'][0]['metadata'][
            'name'] == 'target-00-rootdisk'
        assert 'storageClassName' not in manifest['spec'][
            'dataVolumeTemplates'][0]['spec']['storage']

    def test_vm_manifest_with_udn(self):
        manifest = openshift.get_vm_manifest(
            namespace='ns',
            vm_name='target-00',
            cloud_init_user_data='#cloud-config\n',
            cpu_cores=2,
            memory='2Gi',
            datasource='centos-stream9',
            datasource_namespace='openshift-virtualization-os-images',
            root_storage_size='30Gi',
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

    def test_user_data_files_define_login(self):
        files = list(USER_DATA_DIR.glob('ocp-*-user-data.txt'))
        assert files, f'no user_data templates in {USER_DATA_DIR}'
        for path in files:
            text = path.read_text()
            assert '{user_name}' not in text
            assert '{ssh_pub_key}' not in text
            assert 'ssh_authorized_keys:' in text
            assert 'name: ubuntu' in text
            assert 'volumes:' in text

    def test_user_data_file_splits_volumes_from_cloud_init(self):
        path = USER_DATA_DIR / 'ocp-centos-9.stream-user-data.txt'
        cloud_init, volumes = openshift.parse_user_data_file(str(path))
        assert volumes == [
            {'count': 3, 'size': 15},
            {'count': 2, 'size': 20},
        ]
        assert 'volumes:' not in cloud_init
        assert 'ssh_authorized_keys:' in cloud_init
        assert cloud_init.startswith('#cloud-config')

    def test_normalize_volumes_single_mapping(self):
        assert openshift._normalize_volumes_spec(
            {'count': 3, 'size': 10}
        ) == [{'count': 3, 'size': 10}]

    def test_vm_manifest_with_extra_volumes(self):
        manifest = openshift.get_vm_manifest(
            namespace='ns',
            vm_name='target-00',
            cloud_init_user_data='#cloud-config\n',
            cpu_cores=2,
            memory='2Gi',
            datasource='centos-stream9',
            datasource_namespace='openshift-virtualization-os-images',
            root_storage_size='30Gi',
            extra_volumes=[
                {'count': 3, 'size': 15},
                {'count': 2, 'size': 20},
            ],
        )
        templates = manifest['spec']['dataVolumeTemplates']
        disks = manifest['spec']['template']['spec']['domain']['devices']['disks']
        volumes = manifest['spec']['template']['spec']['volumes']
        names = [
            'target-00-vol-0',
            'target-00-vol-1',
            'target-00-vol-2',
            'target-00-vol-3',
            'target-00-vol-4',
        ]
        assert [t['metadata']['name'] for t in templates] == [
            'target-00-rootdisk', *names
        ]
        sizes = [
            t['spec']['storage']['resources']['requests']['storage']
            for t in templates[1:]
        ]
        assert sizes == ['15Gi', '15Gi', '15Gi', '20Gi', '20Gi']
        assert templates[1]['spec']['source'] == {'blank': {}}
        assert [d['name'] for d in disks][-5:] == names
        assert [v['name'] for v in volumes][-5:] == names

    def test_vm_manifest_storage_classes(self):
        manifest = openshift.get_vm_manifest(
            namespace='ns',
            vm_name='target-00',
            cloud_init_user_data='#cloud-config\n',
            cpu_cores=2,
            memory='2Gi',
            datasource='centos-stream9',
            datasource_namespace='openshift-virtualization-os-images',
            root_storage_size='30Gi',
            extra_volumes=[{'count': 2, 'size': 15}],
            root_storage_class='root-sc',
            data_storage_class='osd-sc',
        )
        templates = manifest['spec']['dataVolumeTemplates']
        assert templates[0]['spec']['storage']['storageClassName'] == 'root-sc'
        assert templates[1]['spec']['storage']['storageClassName'] == 'osd-sc'
        assert templates[2]['spec']['storage']['storageClassName'] == 'osd-sc'

    def test_vcpus_and_ram_from_config(self, monkeypatch):
        class FakeConfig:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {'vcpus': 4, 'ram': 8}
                return default

        monkeypatch.setattr(openshift, 'config', FakeConfig())
        assert openshift.get_vcpus() == 4
        assert openshift.get_ram() == '8Gi'

    def test_required_openshift_keys(self, monkeypatch):
        class FakeConfig:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {}
                return default

        monkeypatch.setattr(openshift, 'config', FakeConfig())
        try:
            openshift.get_vcpus()
            assert False, 'expected RuntimeError'
        except RuntimeError as exc:
            assert 'openshift.vcpus' in str(exc)

    def test_client_configuration_from_service_account(self, monkeypatch, tmp_path):
        import base64
        import os
        ca = base64.b64encode(b'-----BEGIN CERTIFICATE-----\nMII\n').decode()

        class FakeConfig:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {
                        'server': 'https://api.example.com:6443/',
                        'token': 's3cret',
                        'certificate_authority_data': ca,
                    }
                return default

        monkeypatch.setattr(openshift, 'config', FakeConfig())
        cfg = openshift._client_configuration()
        assert cfg.host == 'https://api.example.com:6443'
        assert cfg.api_key['authorization'] == 's3cret'
        assert cfg.api_key_prefix['authorization'] == 'Bearer'
        assert cfg.verify_ssl is True
        assert os.path.exists(cfg.ssl_ca_cert)
        again = openshift._write_ca_file(ca)
        assert again == cfg.ssl_ca_cert

    def test_client_configuration_insecure_without_ca(self, monkeypatch):
        class FakeConfig:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {
                        'server': 'https://api.example.com:6443',
                        'token': 's3cret',
                    }
                return default

        monkeypatch.setattr(openshift, 'config', FakeConfig())
        cfg = openshift._client_configuration()
        assert cfg.verify_ssl is False
