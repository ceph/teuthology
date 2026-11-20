from pathlib import Path

import yaml

from teuthology.provision import openshift

USER_DATA_DIR = Path(__file__).resolve().parents[2] / 'teuthology' / 'ocp' / 'user_data'


class TestOpenShiftHelpers:
    def _manifest_kwargs(self, **overrides):
        kwargs = dict(
            namespace='ns',
            vm_name='target-00',
            cloud_init_user_data='#cloud-config\n',
            cpu_cores=2,
            memory='2Gi',
            datasource='centos-stream9',
            datasource_namespace='openshift-virtualization-os-images',
            root_storage_size='30Gi',
            root_storage_class='root-sc',
            data_storage_class='osd-sc',
            udn_name='vlan1338-front',
            mac_address='52:54:00:14:c2:01',
            udn_binding='l2bridge',
        )
        kwargs.update(overrides)
        return kwargs

    def test_vm_manifest_basic(self):
        manifest = openshift.get_vm_manifest(**self._manifest_kwargs())
        assert manifest['metadata']['name'] == 'target-00'
        assert manifest['spec']['runStrategy'] == 'Always'
        assert 'running' not in manifest['spec']
        tmpl = manifest['spec']['template']['spec']
        assert tmpl['evictionStrategy'] == 'None'
        # Single Multus NIC only — no pod/masquerade (tracker #80437)
        assert tmpl['domain']['devices']['interfaces'] == [{
            'name': 'vlan1338-front',
            'macAddress': '52:54:00:14:c2:01',
            'binding': {'name': 'l2bridge'},
        }]
        assert tmpl['networks'] == [{
            'name': 'vlan1338-front',
            'multus': {'networkName': 'vlan1338-front'},
        }]
        root = manifest['spec']['dataVolumeTemplates'][0]
        assert root['metadata']['name'] == 'target-00-rootdisk'
        assert root['spec']['storage']['storageClassName'] == 'root-sc'
        cloud_init = tmpl['volumes'][1]['cloudInitNoCloud']
        assert cloud_init == {'userData': '#cloud-config\n'}

    def test_vm_manifest_requires_udn(self):
        try:
            openshift.get_vm_manifest(**self._manifest_kwargs(udn_name=''))
            assert False, 'expected RuntimeError'
        except RuntimeError as exc:
            assert 'udn_name is required' in str(exc)

    def test_user_data_files_are_cloud_init_only(self):
        """Templates must be cloud-init (+ optional network), not site policy."""
        files = list(USER_DATA_DIR.glob('ocp-*-user-data.txt'))
        assert files, f'no user_data templates in {USER_DATA_DIR}'
        for path in files:
            text = path.read_text()
            data = yaml.safe_load(text) or {}
            assert text.lstrip().startswith('#cloud-config')
            assert 'ssh_authorized_keys' not in text
            assert 'volumes' not in data
            assert 'datasource' not in data
            cloud_init, network_data = openshift.parse_user_data_file(str(path))
            assert cloud_init.startswith('#cloud-config')
            assert 'volumes:' not in cloud_init
            assert 'datasource:' not in cloud_init
            assert 'network:' not in cloud_init
            if 'network' in yaml.safe_load(text):
                assert network_data is not None


    def test_user_data_file_splits_network_data(self):
        path = USER_DATA_DIR / 'ocp-centos-9.stream-user-data.txt'
        key = 'ssh-ed25519 AAAA test@teuthology'
        cloud_init, network_data = openshift.parse_user_data_file(
            str(path),
            ssh_authorized_keys=[key],
        )
        assert 'volumes:' not in cloud_init
        assert 'datasource:' not in cloud_init
        assert 'network:' not in cloud_init
        assert 'ssh_authorized_keys:' in cloud_init
        assert key in cloud_init
        assert cloud_init.startswith('#cloud-config')
        assert network_data == (
            'version: 2\n'
            'ethernets:\n'
            '  all-en:\n'
            '    match:\n'
            '      name: en*\n'
            '    dhcp4: true\n'
        )

    def test_user_data_rejects_volumes_or_datasource(self, tmp_path):
        path = tmp_path / 'bad-user-data.txt'
        path.write_text('#cloud-config\nvolumes:\n  count: 1\n  size: 10\n')
        try:
            openshift.parse_user_data_file(str(path))
            assert False, 'expected RuntimeError'
        except RuntimeError as exc:
            assert 'volumes' in str(exc)

    def test_ssh_authorized_keys_from_config(self, monkeypatch):
        class FakeConfig:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {
                        'ssh_authorized_keys': [
                            'ssh-ed25519 AAAA one@host',
                            'ssh-ed25519 BBBB two@host',
                        ],
                    }
                return default

        monkeypatch.setattr(openshift, 'config', FakeConfig())
        assert openshift.get_ssh_authorized_keys() == [
            'ssh-ed25519 AAAA one@host',
            'ssh-ed25519 BBBB two@host',
        ]

        path = USER_DATA_DIR / 'ocp-ubuntu-22.04-user-data.txt'
        cloud_init, _ = openshift.parse_user_data_file(
            str(path),
            ssh_authorized_keys=openshift.get_ssh_authorized_keys(),
        )
        assert 'ssh-ed25519 AAAA one@host' in cloud_init
        assert 'ssh-ed25519 BBBB two@host' in cloud_init

    def test_volumes_and_datasources_from_config(self, monkeypatch):
        class FakeConfig:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {
                        'volumes': [
                            {'count': 3, 'size': 15},
                            {'count': 2, 'size': 20},
                        ],
                        'datasources': {
                            'ubuntu/22.04': 'ubuntu-22.04',
                            'centos/9.stream': 'centos-stream9',
                        },
                    }
                return default

        monkeypatch.setattr(openshift, 'config', FakeConfig())
        assert openshift.get_volumes() == [
            {'count': 3, 'size': 15},
            {'count': 2, 'size': 20},
        ]
        assert openshift.get_datasource_name('ubuntu', '22.04') == \
            'ubuntu-22.04'
        assert openshift.get_datasource_name('centos', '9.stream') == \
            'centos-stream9'
        try:
            openshift.get_datasource_name('rocky', '10')
            assert False, 'expected RuntimeError'
        except RuntimeError as exc:
            assert 'rocky/10' in str(exc)

    def test_ubuntu_user_data_keeps_guest_agent_package(self):
        path = USER_DATA_DIR / 'ocp-ubuntu-24.04-user-data.txt'
        cloud_init, network_data = openshift.parse_user_data_file(str(path))
        assert 'packages:\n- qemu-guest-agent\n' in cloud_init
        assert network_data is not None
        assert 'network:' not in cloud_init

    def test_vm_manifest_passes_network_data_to_cloud_init(self):
        manifest = openshift.get_vm_manifest(**self._manifest_kwargs(
            cloud_init_user_data=(
                '#cloud-config\npackages:\n- qemu-guest-agent\n'
            ),
            cloud_init_network_data=(
                'version: 2\n'
                'ethernets:\n'
                '  all-en:\n'
                '    match:\n'
                '      name: en*\n'
                '    dhcp4: true\n'
            ),
            datasource='ubuntu-24.04',
            datasource_namespace='ns',
        ))
        cloud_init = manifest['spec']['template']['spec']['volumes'][1][
            'cloudInitNoCloud'
        ]
        assert cloud_init['userData'].startswith('#cloud-config')
        assert cloud_init['networkData'].startswith('version: 2')

    def test_normalize_volumes_single_mapping(self):
        assert openshift._normalize_volumes_spec(
            {'count': 3, 'size': 10}
        ) == [{'count': 3, 'size': 10}]

    def test_enabled_requires_full_config(self, monkeypatch):
        class PartialConfig:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {
                        'namespace': 'ns',
                        'machine_types': ['ocpvirt'],
                    }
                return default

        monkeypatch.setattr(openshift, 'config', PartialConfig())
        assert openshift.enabled() is False
        unset = openshift._unset_required_keys({
            'namespace': 'ns',
            'machine_types': ['ocpvirt'],
        })
        assert 'server' in unset
        assert 'volumes' in unset
        assert 'datasources' in unset

        complete = {
            key: 'x' for key in openshift._REQUIRED_CONF_KEYS
            if key not in ('machine_types', 'volumes', 'datasources',
                           'ssh_authorized_keys')
        }
        complete.update({
            'machine_types': ['ocpvirt'],
            'volumes': [],
            'datasources': {'ubuntu/22.04': 'ubuntu-22.04'},
            'ssh_authorized_keys': ['ssh-ed25519 AAAA'],
        })
        assert openshift._unset_required_keys(complete) == []

    def test_datasource_namespace_required(self, monkeypatch):
        class FakeConfig:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {'namespace': 'guest-ns'}
                return default

        monkeypatch.setattr(openshift, 'config', FakeConfig())
        try:
            openshift.get_datasource_namespace()
            assert False, 'expected RuntimeError'
        except RuntimeError as exc:
            assert 'openshift.datasource_namespace' in str(exc)

        class WithDatasourceNamespace:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {
                        'datasource_namespace':
                            'openshift-virtualization-os-images',
                    }
                return default

        monkeypatch.setattr(openshift, 'config', WithDatasourceNamespace())
        assert openshift.get_datasource_namespace() == \
            'openshift-virtualization-os-images'

    def test_udn_name_required(self, monkeypatch):
        class FakeConfig:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {}
                return default

        monkeypatch.setattr(openshift, 'config', FakeConfig())
        try:
            openshift.get_udn_name()
            assert False, 'expected RuntimeError'
        except RuntimeError as exc:
            assert 'openshift.udn_name' in str(exc)

        class WithUdn:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {'udn_name': 'lab-udn'}
                return default

        monkeypatch.setattr(openshift, 'config', WithUdn())
        assert openshift.get_udn_name() == 'lab-udn'

    def test_timeout_from_config(self, monkeypatch):
        class FakeConfig:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {}
                return default

        monkeypatch.setattr(openshift, 'config', FakeConfig())
        assert openshift.get_timeout() == 900

        class WithTimeout:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {'timeout': 1800}
                return default

        monkeypatch.setattr(openshift, 'config', WithTimeout())
        assert openshift.get_timeout() == 1800

    def test_vm_manifest_with_extra_volumes(self):
        manifest = openshift.get_vm_manifest(**self._manifest_kwargs(
            extra_volumes=[
                {'count': 3, 'size': 15},
                {'count': 2, 'size': 20},
            ],
        ))
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
        # cloud-init must be a SATA CD-ROM so zap_disks skips it (sr*)
        cloudinit = next(d for d in disks if d['name'] == 'cloudinitdisk')
        assert cloudinit.get('cdrom') == {'bus': 'sata'}
        assert 'disk' not in cloudinit

    def test_vm_manifest_storage_classes(self):
        manifest = openshift.get_vm_manifest(**self._manifest_kwargs(
            extra_volumes=[{'count': 2, 'size': 15}],
        ))
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
        import stat
        ca = base64.b64encode(b'-----BEGIN CERTIFICATE-----\nMII\n').decode()
        monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))

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
        assert cfg.api_key['BearerToken'] == 's3cret'
        assert cfg.api_key_prefix['BearerToken'] == 'Bearer'
        assert cfg.verify_ssl is True
        assert os.path.exists(cfg.ssl_ca_cert)
        assert str(tmp_path) in cfg.ssl_ca_cert
        assert stat.S_IMODE(os.stat(os.path.dirname(cfg.ssl_ca_cert)).st_mode) == 0o700
        again = openshift._write_ca_file(ca)
        assert again == cfg.ssl_ca_cert

    def test_write_ca_file_rejects_content_mismatch(self, monkeypatch, tmp_path):
        import base64
        import os
        pem = b'-----BEGIN CERTIFICATE-----\nREAL\n-----END CERTIFICATE-----\n'
        planted = b'-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----\n'
        assert len(pem) == len(planted)
        ca = base64.b64encode(pem).decode()
        monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
        cache_dir = openshift._ca_cache_dir()
        digest = __import__('hashlib').sha256(pem).hexdigest()[:16]
        path = os.path.join(cache_dir, f'{digest}.crt')
        with open(path, 'wb') as handle:
            handle.write(planted)
        written = openshift._write_ca_file(ca)
        assert written == path
        with open(path, 'rb') as handle:
            assert handle.read() == pem

    def test_client_configuration_verifies_tls_without_ca(self, monkeypatch):
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
        assert cfg.verify_ssl is True
        assert not getattr(cfg, 'ssl_ca_cert', None)

    def test_client_configuration_insecure_skip_tls_verify(self, monkeypatch):
        class FakeConfig:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {
                        'server': 'https://api.example.com:6443',
                        'token': 's3cret',
                        'insecure_skip_tls_verify': True,
                    }
                return default

        monkeypatch.setattr(openshift, 'config', FakeConfig())
        cfg = openshift._client_configuration()
        assert cfg.verify_ssl is False

    def _openshift_stub(self, udn_name=''):
        obj = object.__new__(openshift.OpenShift)
        obj.name = 'target-015.example.com'
        obj.shortname = 'target-015'
        obj.vm_name = 'target-015'
        obj.namespace = 'ns'
        obj.group = 'kubevirt.io'
        obj.version = 'v1'
        obj.plural = 'virtualmachines'
        obj.vmi_plural = 'virtualmachineinstances'
        obj.os_type = 'ubuntu'
        obj.os_version = '22.04'
        obj._objects_api = None
        obj._core_api = None
        obj._remote = None
        obj._mac_address = None
        obj._mac_loaded = False
        obj._udn_name = None
        obj._udn_binding = None
        obj.udn_name = udn_name
        obj.log = openshift.log.getChild('target-015')
        return obj

    def test_create_success_path(self, monkeypatch):
        obj = self._openshift_stub(udn_name='teuthology-net')
        calls = []

        monkeypatch.setattr(openshift, 'get_vcpus', lambda: 2)
        monkeypatch.setattr(openshift, 'get_ram', lambda: '4Gi')
        monkeypatch.setattr(
            obj, 'delete',
            lambda: calls.append('delete') or True,
        )
        monkeypatch.setattr(
            obj, '_wait_for_deleted',
            lambda: calls.append('wait_deleted'),
        )
        monkeypatch.setattr(
            obj, 'provision',
            lambda **kwargs: calls.append('provision'),
        )
        monkeypatch.setattr(
            obj, '_wait_for_status',
            lambda status: calls.append(f'wait_{status.lower()}'),
        )
        monkeypatch.setattr(
            obj, '_wait_for_ip_address',
            lambda: calls.append('wait_ip') or '192.168.14.10',
        )
        monkeypatch.setattr(
            obj, '_wait_for_ready',
            lambda: calls.append('wait_ready'),
        )

        name, ip = obj.create()
        assert name == obj.name
        assert ip == '192.168.14.10'
        assert calls == [
            'delete',
            'wait_deleted',
            'provision',
            'wait_running',
            'wait_ip',
            'wait_ready',
        ]

    def test_create_cleans_up_on_failure(self, monkeypatch):
        obj = self._openshift_stub()
        obj.os_type = 'ubuntu'
        obj.os_version = '22.04'
        obj.name = 'target-015.example.com'
        released = {'n': 0}

        monkeypatch.setattr(obj, 'delete', lambda: True)
        monkeypatch.setattr(obj, '_wait_for_deleted', lambda: None)
        monkeypatch.setattr(
            openshift, 'get_vcpus', lambda: 2
        )
        monkeypatch.setattr(
            openshift, 'get_ram', lambda: '4Gi'
        )

        def boom(*args, **kwargs):
            raise RuntimeError('provision failed')

        monkeypatch.setattr(obj, 'provision', boom)

        def fake_release():
            released['n'] += 1

        monkeypatch.setattr(obj, 'release', fake_release)
        try:
            obj.create()
            assert False, 'expected RuntimeError'
        except RuntimeError as exc:
            assert 'provision failed' in str(exc)
        assert released['n'] == 1

    def test_release_deletes_then_waits(self, monkeypatch):
        obj = self._openshift_stub()
        calls = []
        monkeypatch.setattr(
            obj, 'delete',
            lambda: calls.append('delete') or True,
        )
        monkeypatch.setattr(
            obj, '_wait_for_deleted',
            lambda: calls.append('wait_deleted'),
        )
        obj.release()
        assert calls == ['delete', 'wait_deleted']

    def test_get_provisioner_object_routes_openshift(self, monkeypatch):
        from teuthology.provision import get_provisioner_object

        monkeypatch.setattr(openshift, 'get_types', lambda: ['ocpvirt'])
        monkeypatch.setattr(
            'teuthology.provision.fog.get_types', lambda: [],
        )
        monkeypatch.setattr(
            'teuthology.provision.maas.get_types', lambda: [],
        )
        monkeypatch.setattr(
            'teuthology.provision.pelagos.get_types', lambda: [],
        )
        created = {}

        class FakeOpenShift:
            def __init__(self, name, os_type, os_version):
                created['args'] = (name, os_type, os_version)

        monkeypatch.setattr(openshift, 'OpenShift', FakeOpenShift)
        obj = get_provisioner_object(
            'ocpvirt', 'target-015', 'ubuntu', '22.04',
        )
        assert isinstance(obj, FakeOpenShift)
        assert created['args'] == ('target-015', 'ubuntu', '22.04')

    def test_delete_uses_foreground_propagation(self, monkeypatch):
        class FakeApiException(Exception):
            def __init__(self, status):
                self.status = status

        class FakeObjectsApi:
            def __init__(self):
                self.kwargs = None

            def delete_namespaced_custom_object(self, **kwargs):
                self.kwargs = kwargs

        class FakeClient:
            ApiException = FakeApiException

        obj = self._openshift_stub()
        api = FakeObjectsApi()
        obj._objects_api = api
        monkeypatch.setattr(openshift, '_kubernetes_client', lambda: FakeClient())
        assert obj.delete() is True
        assert api.kwargs['propagation_policy'] == 'Foreground'
        assert api.kwargs['name'] == 'target-015'

    def test_wait_for_deleted_waits_for_storage(self, monkeypatch):
        obj = self._openshift_stub()
        calls = {'n': 0}

        def fake_resource_exists(**kwargs):
            calls['n'] += 1
            # First pass: VM gone, rootdisk DV still present.
            # Second pass: everything gone.
            if calls['n'] == 1:
                return kwargs.get('plural') == 'datavolumes'
            return False

        monkeypatch.setattr(obj, '_resource_exists', fake_resource_exists)
        monkeypatch.setattr(
            obj, '_owned_storage_names',
            lambda: ['target-015-rootdisk'],
        )
        # Avoid real sleep/timeouts from safe_while
        class Immediate:
            def __enter__(self):
                self.left = 2
                return self

            def __exit__(self, *args):
                return False

            def __call__(self):
                if self.left <= 0:
                    return False
                self.left -= 1
                return True

        monkeypatch.setattr(
            openshift, 'safe_while',
            lambda **kwargs: Immediate(),
        )
        obj._wait_for_deleted(timeout=1, interval=0)
        assert calls['n'] >= 2

    def test_wait_for_status_keeps_polling_through_other_statuses(
            self, monkeypatch):
        obj = self._openshift_stub(udn_name='teuthology-net')
        statuses = iter(['DataVolumeError', 'Provisioning', 'Running'])

        class FakeObjectsApi:
            def get_namespaced_custom_object(self, **kwargs):
                return {
                    'status': {'printableStatus': next(statuses)},
                }

        class Immediate:
            def __enter__(self):
                self.left = 5
                return self

            def __exit__(self, *args):
                return False

            def __call__(self):
                if self.left <= 0:
                    return False
                self.left -= 1
                return True

        obj._objects_api = FakeObjectsApi()
        monkeypatch.setattr(openshift, '_kubernetes_client', lambda: object())
        monkeypatch.setattr(
            openshift, 'safe_while',
            lambda **kwargs: Immediate(),
        )
        obj._wait_for_status('Running', timeout=1, interval=0)

    def test_get_ip_from_vmi_requires_udn_when_configured(self):
        obj = self._openshift_stub(udn_name='teuthology-net')
        vmi = {
            'status': {
                'interfaces': [
                    {
                        'name': 'default',
                        'ipAddress': '172.16.89.103',
                        'ipAddresses': ['172.16.89.103'],
                    },
                    {
                        'name': 'teuthology-net',
                        # UDN iface present but not yet addressed
                    },
                ],
            },
        }
        assert obj._get_ip_from_vmi(vmi) is None

    def test_get_ip_from_vmi_returns_udn_ip(self):
        obj = self._openshift_stub(udn_name='teuthology-net')
        vmi = {
            'status': {
                'interfaces': [
                    {
                        'name': 'default',
                        'ipAddress': '172.16.89.103',
                    },
                    {
                        'name': 'teuthology-net',
                        'ipAddress': '192.168.14.42',
                        'ipAddresses': ['192.168.14.42'],
                    },
                ],
            },
        }
        assert obj._get_ip_from_vmi(vmi) == '192.168.14.42'

    def test_get_ip_from_vmi_ignores_other_non_default_without_udn_match(self):
        obj = self._openshift_stub(udn_name='teuthology-net')
        vmi = {
            'status': {
                'interfaces': [
                    {'name': 'default', 'ipAddress': '172.16.89.103'},
                    {'name': 'other-net', 'ipAddress': '10.0.0.5'},
                ],
            },
        }
        assert obj._get_ip_from_vmi(vmi) is None

    def test_get_ip_from_vmi_without_udn_returns_none(self):
        obj = self._openshift_stub(udn_name='')
        vmi = {
            'status': {
                'interfaces': [
                    {'name': 'default', 'ipAddress': '172.16.89.103'},
                    {'name': 'teuthology-net', 'ipAddress': '192.168.14.42'},
                ],
            },
        }
        assert obj._get_ip_from_vmi(vmi) is None

    def test_wait_for_ready_retries_stale_host_key(self, monkeypatch):
        from paramiko.ssh_exception import BadHostKeyException
        from unittest.mock import MagicMock

        obj = self._openshift_stub(udn_name='teuthology-net')
        obj.name = 'target-015.example.com'
        obj.os_type = 'ubuntu'
        obj.os_version = '22.04'
        removed = {'n': 0}
        connects = {'n': 0}

        class FakeRemote:
            shortname = 'target-015'
            os = __import__(
                'teuthology.orchestra.opsys', fromlist=['OS']
            ).OS(name='ubuntu', version='22.04')

            def connect(self):
                connects['n'] += 1
                if connects['n'] == 1:
                    got = MagicMock()
                    expected = MagicMock()
                    got.get_base64.return_value = 'got'
                    expected.get_base64.return_value = 'exp'
                    raise BadHostKeyException(
                        'target-015.example.com', got, expected
                    )

        class Immediate:
            def __enter__(self):
                self.left = 3
                return self

            def __exit__(self, *args):
                return False

            def __call__(self):
                if self.left <= 0:
                    return False
                self.left -= 1
                return True

        obj._remote = FakeRemote()
        monkeypatch.setattr(
            openshift, 'safe_while',
            lambda **kwargs: Immediate(),
        )
        monkeypatch.setattr(
            openshift.misc, 'ssh_keygen_remove',
            lambda name: removed.__setitem__('n', removed['n'] + 1),
        )
        monkeypatch.setattr(
            openshift, 'config',
            type('C', (), {'get': staticmethod(lambda *a, **k: {})})(),
        )
        obj._wait_for_ready(timeout=1)
        assert removed['n'] == 1
        assert connects['n'] >= 2

    def test_enabled_false_without_kubernetes(self, monkeypatch):
        class FakeConfig:
            def get(self, key, default=None):
                if key == 'openshift':
                    return {
                        'namespace': 'ns',
                        'machine_types': ['ocpvirt'],
                    }
                return default

        monkeypatch.setattr(openshift, '_k8s_client', None)
        monkeypatch.setattr(openshift, 'config', FakeConfig())
        assert openshift.enabled(warn=True) is False
        assert openshift.get_types() == []
        try:
            openshift._kubernetes_client()
            assert False, 'expected RuntimeError'
        except RuntimeError as exc:
            assert '[openshift]' in str(exc)

    def test_import_provision_without_kubernetes(self, monkeypatch):
        """teuthology.provision must import even if kubernetes is absent."""
        import builtins
        import importlib
        import sys

        saved = {
            mod: sys.modules[mod]
            for mod in list(sys.modules)
            if (
                mod == 'kubernetes'
                or mod.startswith('kubernetes.')
                or mod == 'teuthology.provision'
                or mod.startswith('teuthology.provision.')
            )
        }
        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(),
                        level=0):
            if name == 'kubernetes' or name.startswith('kubernetes.'):
                raise ImportError(f'No module named {name!r}')
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, '__import__', fake_import)
        for mod in list(saved):
            del sys.modules[mod]

        try:
            provision = importlib.import_module('teuthology.provision')
            ocp = importlib.import_module('teuthology.provision.openshift')
            assert ocp._k8s_client is None
            assert ocp.enabled() is False
            assert ocp.get_types() == []
            assert provision.openshift is ocp
        finally:
            for mod in list(sys.modules):
                if (
                    mod == 'teuthology.provision'
                    or mod.startswith('teuthology.provision.')
                ):
                    del sys.modules[mod]
            sys.modules.update(saved)
