import contextlib
import os
import pytest
import yaml

from mock import patch, Mock
from pytest import mark

from teuthology.task import install
from teuthology.task.install import deb


class TestInstall(object):

    def _get_default_package_list(self, project='ceph', debug=False):
        path = os.path.join(
            os.path.dirname(__file__),
            '..', '..', 'teuthology', 'task', 'install', 'packages.yaml',
        )
        pkgs = yaml.safe_load(open(path))[project]
        if not debug:
            pkgs['deb'] = [p for p in pkgs['deb']
                                        if not p.endswith('-dbg')]
            pkgs['rpm'] = [p for p in pkgs['rpm']
                                        if not p.endswith('-debuginfo')]
        return pkgs

    def test_get_package_list_debug(self):
        default_pkgs = self._get_default_package_list(debug=True)
        default_pkgs['rpm'].sort()
        default_pkgs['deb'].sort()
        config = dict(debuginfo=True)
        result = install.get_package_list(ctx=None, config=config)
        result['rpm'].sort()
        result['deb'].sort()
        assert result == default_pkgs

    def test_get_package_list_no_debug(self):
        default_pkgs = self._get_default_package_list(debug=False)
        default_pkgs['rpm'].sort()
        default_pkgs['deb'].sort()
        config = dict(debuginfo=False)
        result = install.get_package_list(ctx=None, config=config)
        result['rpm'].sort()
        result['deb'].sort()
        assert result == default_pkgs

    def test_get_package_list_custom_rpm(self):
        default_pkgs = self._get_default_package_list(debug=False)
        default_pkgs['rpm'].sort()
        default_pkgs['deb'].sort()
        rpms = ['rpm1', 'rpm2', 'rpm2-debuginfo']
        config = dict(packages=dict(rpm=rpms))
        result = install.get_package_list(ctx=None, config=config)
        result['rpm'].sort()
        result['deb'].sort()
        assert result['rpm'] == ['rpm1', 'rpm2']
        assert result['deb'] == default_pkgs['deb']

    @patch("teuthology.task.install._get_builder_project")
    @patch("teuthology.task.install.packaging.get_package_version")
    def test_get_upgrade_version(self, m_get_package_version,
                                         m_gitbuilder_project):
        gb = Mock()
        gb.version = "11.0.0"
        gb.project = "ceph"
        m_gitbuilder_project.return_value = gb
        m_get_package_version.return_value = "11.0.0"
        install.get_upgrade_version(Mock(), Mock(), Mock())

    @patch("teuthology.task.install._get_builder_project")
    @patch("teuthology.task.install.packaging.get_package_version")
    def test_verify_ceph_version_success(self, m_get_package_version,
                                         m_gitbuilder_project):
        gb = Mock()
        gb.version = "0.89.0"
        gb.project = "ceph"
        m_gitbuilder_project.return_value = gb
        m_get_package_version.return_value = "0.89.0"
        config = dict()
        install.verify_package_version(Mock(), config, Mock())

    @patch("teuthology.task.install._get_builder_project")
    @patch("teuthology.task.install.packaging.get_package_version")
    def test_verify_ceph_version_failed(self, m_get_package_version,
                                        m_gitbuilder_project):
        gb = Mock()
        gb.version = "0.89.0"
        gb.project = "ceph"
        m_gitbuilder_project.return_value = gb
        m_get_package_version.return_value = "0.89.1"
        config = dict()
        with pytest.raises(RuntimeError):
            install.verify_package_version(Mock(), config, Mock())

    def test_get_flavor_default(self):
        config = dict()
        assert install.get_flavor(config) == 'default'

    def test_get_flavor_simple(self):
        config = dict(
            flavor='notcmalloc'
        )
        assert install.get_flavor(config) == 'notcmalloc'

    def test_get_flavor_valgrind(self):
        config = dict(
            valgrind=True
        )
        assert install.get_flavor(config) == 'notcmalloc'

    def test_upgrade_is_downgrade(self):
        assert_ok_vals = [
            ('9.0.0', '10.0.0'),
            ('10.2.2-63-g8542898-1trusty', '10.2.2-64-gabcdef1-1trusty'),
            ('11.0.0-918.g13c13c7', '11.0.0-2165.gabcdef1')
        ]
        for t in assert_ok_vals:
            assert install._upgrade_is_downgrade(t[0], t[1]) == False

    @patch("teuthology.packaging.get_package_version")
    @patch("teuthology.misc.get_system_type")
    @patch("teuthology.task.install.verify_package_version")
    @patch("teuthology.task.install.get_upgrade_version")
    def test_upgrade_common(self,
                            m_get_upgrade_version,
                            m_verify_package_version,
                            m_get_system_type,
                            m_get_package_version):
        expected_system_type = 'deb'
        def make_remote():
            remote = Mock()
            remote.arch = 'x86_64'
            remote.os = Mock()
            remote.os.name = 'ubuntu'
            remote.os.version = '14.04'
            remote.os.codename = 'trusty'
            remote.system_type = expected_system_type
            return remote
        ctx = Mock()
        class cluster:
            remote1 = make_remote()
            remote2 = make_remote()
            remotes = {
                remote1: ['client.0'],
                remote2: ['mon.a','osd.0'],
            }
            def only(self, role):
                result = Mock()
                if role in ('client.0',):
                    result.remotes = { cluster.remote1: None }
                if role in ('osd.0', 'mon.a'):
                    result.remotes = { cluster.remote2: None }
                return result
        ctx.cluster = cluster()
        config = {
            'client.0': {
                'sha1': 'expectedsha1',
            },
        }
        ctx.config = {
            'roles': [ ['client.0'], ['mon.a','osd.0'] ],
            'tasks': [
                {
                    'install.upgrade': config,
                },
            ],
        }
        m_get_upgrade_version.return_value = "11.0.0"
        m_get_package_version.return_value = "10.2.4"
        m_get_system_type.return_value = "deb"
        def upgrade(ctx, node, remote, pkgs, system_type):
            assert system_type == expected_system_type
        assert install.upgrade_common(ctx, config, upgrade) == 1
        expected_config = {
            'project': 'ceph',
            'sha1': 'expectedsha1',
        }
        m_verify_package_version.assert_called_with(ctx,
                                                    expected_config,
                                                    cluster.remote1)
    def test_upgrade_remote_to_config(self):
        expected_system_type = 'deb'
        def make_remote():
            remote = Mock()
            remote.arch = 'x86_64'
            remote.os = Mock()
            remote.os.name = 'ubuntu'
            remote.os.version = '14.04'
            remote.os.codename = 'trusty'
            remote.system_type = expected_system_type
            return remote
        ctx = Mock()
        class cluster:
            remote1 = make_remote()
            remote2 = make_remote()
            remotes = {
                remote1: ['client.0'],
                remote2: ['mon.a','osd.0'],
            }
            def only(self, role):
                result = Mock()
                if role in ('client.0',):
                    result.remotes = { cluster.remote1: None }
                elif role in ('osd.0', 'mon.a'):
                    result.remotes = { cluster.remote2: None }
                else:
                    result.remotes = None
                return result
        ctx.cluster = cluster()
        ctx.config = {
            'roles': [ ['client.0'], ['mon.a','osd.0'] ],
        }

        # nothing -> nothing
        assert install.upgrade_remote_to_config(ctx, {}) == {}

        # select the remote for the osd.0 role
        # the 'ignored' role does not exist and is ignored
        # the remote for mon.a is the same as for osd.0 and
        # is silently ignored (actually it could be the other
        # way around, depending on how the keys are hashed)
        config = {
            'osd.0': {
                'sha1': 'expectedsha1',
            },
            'ignored': None,
            'mon.a': {
                'sha1': 'expectedsha1',
            },
        }
        expected_config = {
            cluster.remote2: {
                'project': 'ceph',
                'sha1': 'expectedsha1',
            },
        }
        assert install.upgrade_remote_to_config(ctx, config) == expected_config

        # select all nodes, regardless
        config = {
            'all': {
                'sha1': 'expectedsha1',
            },
        }
        expected_config = {
            cluster.remote1: {
                'project': 'ceph',
                'sha1': 'expectedsha1',
            },
            cluster.remote2: {
                'project': 'ceph',
                'sha1': 'expectedsha1',
            },
        }
        assert install.upgrade_remote_to_config(ctx, config) == expected_config

        # verify that install overrides are used as default
        # values for the upgrade task, not as override
        ctx.config['overrides'] = {
            'install': {
                'ceph': {
                    'sha1': 'overridesha1',
                    'tag': 'overridetag',
                    'branch': 'overridebranch',
                },
            },
        }
        config = {
            'client.0': {
                'sha1': 'expectedsha1',
            },
            'osd.0': {
            },
        }
        expected_config = {
            cluster.remote1: {
                'project': 'ceph',
                'sha1': 'expectedsha1',
            },
            cluster.remote2: {
                'project': 'ceph',
                'sha1': 'overridesha1',
                'tag': 'overridetag',
                'branch': 'overridebranch',
            },
        }
        assert install.upgrade_remote_to_config(ctx, config) == expected_config


    @patch("teuthology.task.install.packaging.get_package_version")
    @patch("teuthology.task.install.redhat.set_deb_repo")
    def test_rh_install_deb_pkgs(self, m_set_rh_deb_repo, m_get_pkg_version):
        ctx = Mock()
        remote = Mock()
        version = '1.3.2'
        rh_ds_yaml = dict()
        rh_ds_yaml = {
            'versions': {'deb': {'mapped': {'1.3.2': '0.94.5'}}},
            'pkgs': {'deb': ['pkg1', 'pkg2']},
            'extra_system_packages': {'deb': ['es_pkg1', 'es_pkg2']},
            'extra_packages': {'deb': ['e_pkg1', 'e_pkg2']},
        }
        m_get_pkg_version.return_value = "0.94.5"
        install.redhat.install_deb_pkgs(ctx, remote, version, rh_ds_yaml)

    @patch("teuthology.task.install.packaging.get_package_version")
    def test_rh_install_pkgs(self, m_get_pkg_version):
        ctx = Mock()
        remote = Mock()
        version = '1.3.2'
        rh_ds_yaml = dict()
        rh_ds_yaml = {
            'versions': {'rpm': {'mapped': {'1.3.2': '0.94.5',
                                            '1.3.1': '0.94.3'}}},
            'pkgs': {'rpm': ['pkg1', 'pkg2']},
            'extra_system_packages': {'rpm': ['es_pkg1', 'es_pkg2']},
            'extra_packages': {'rpm': ['e_pkg1', 'e_pkg2']},
        }

        m_get_pkg_version.return_value = "0.94.5"
        install.redhat.install_pkgs(ctx, remote, version, rh_ds_yaml)
        version = '1.3.1'
        with pytest.raises(RuntimeError) as e:
            install.redhat.install_pkgs(ctx, remote, version, rh_ds_yaml)
        assert "Version check failed" in str(e)

    @mark.parametrize(
        'conf, expect',
        [
            [
                {
                    'tasks': [ { 'install': { 'clean': True, }, }, ],
                    'overrides': {
                        'install': {
                            'ceph': {
                                 'extra_system_packages': ['alpha'],
                                 'flavor': 'default',
                                 'sha1': '0123456789abcdef0123456789abcdef01234567',
                             },
                            'extra_system_packages': {
                                'deb': [],
                                'rpm': ['xerxes', 'yellow'],
                            },
                        },
                    },
                },
                {
                    'deb': ['alpha'],
                    'rpm': ['alpha', 'xerxes', 'yellow'],
                }
            ],
            [
                {
                    'tasks': [ { 'install': { 'clean': True, }, }, ],
                    'overrides': {
                        'install': {
                            'ceph': {
                                 'extra_system_packages': {
                                     'deb': [],
                                     'rpm': ['xerxes', 'yellow'],
                                 },
                                 'flavor': 'default',
                                 'sha1': '0123456789abcdef0123456789abcdef01234567',
                             },
                            'extra_system_packages': ['alpha'],
                        },
                    },
                },
                {
                    'deb': ['alpha'],
                    'rpm': ['xerxes', 'yellow', 'alpha'],
                }
            ],
            [
                {
                    'tasks': [ { 'install': { 'clean': True, }, }, ],
                    'overrides': {
                        'install': {
                            'ceph': {
                                 'flavor': 'default',
                                 'sha1': '0123456789abcdef0123456789abcdef01234567',
                             },
                            'extra_system_packages': {
                                'deb': [],
                                'rpm': ['xerxes', 'yellow'],
                            },
                        },
                    },
                },
                {
                    'deb': [],
                    'rpm': ['xerxes', 'yellow'],
                }
            ],
            [
                {
                    'tasks': [ { 'install': { 'clean': True, }, }, ],
                    'overrides': {
                        'install': {
                            'ceph': {
                                 'flavor': 'default',
                                 'sha1': '0123456789abcdef0123456789abcdef01234567',
                             },
                            'extra_system_packages': ['xerxes', 'yellow'],
                        },
                    },
                },
                {
                    'deb': ['xerxes', 'yellow'],
                    'rpm': ['xerxes', 'yellow'],
                }
            ],
            [
                {
                    'tasks': [ { 'install': { 'clean': True, }, }, ],
                    'overrides': { 'install': {
                            'ceph': { 'flavor': 'default', 'sha1': '012345', },
                            'extra_system_packages': { 'rpm': ['xerxes', 'yellow'], },
                        },
                    },
                },
                { 'deb': [], 'rpm': ['xerxes', 'yellow'], }

            ],
            [
                {
                    'tasks': [ { 'install': { 'clean': True,
                                             'extra_system_packages': { 'deb': ['alpha'], 'rpm': ['bravo'] },
                                             }, }, ],
                    'overrides': { 'install': {
                            'ceph': { 'flavor': 'default', 'sha1': '012345', },
                            'extra_system_packages': { 'rpm': ['xerxes', 'yellow'], },
                        },
                    },
                },
                { 'deb': ['alpha'], 'rpm': ['bravo', 'xerxes', 'yellow'], }

            ],

        ]
    )
    def test_install_extra_system_packages(self, conf, expect):
        install_task = conf.get('tasks')[0].get('install')
        install_overrides = conf.get('overrides').get('install', {})
        install._override_extra_system_packages(install_task, 'ceph', install_overrides)

        assert install_task.get('extra_system_packages') == expect


def apt_repo(**kwargs):
    repo = dict(
        name='custom',
        url='https://example.com/ubuntu',
        suite='jammy',
        components=['main'],
        key_url='https://example.com/release.asc',
    )
    repo.update(kwargs)
    return repo


class TestDebCustomRepos(object):

    @pytest.mark.parametrize(
        'repo',
        [
            {k: v for k, v in apt_repo().items() if k != 'suite'},
            apt_repo(priority=1),
            apt_repo(name='../evil'),
            apt_repo(components=[]),
            apt_repo(components='main'),
            apt_repo(suite='./'),
            {k: v for k, v in apt_repo().items() if k != 'components'},
            apt_repo(url='https://example.com/ubuntu jammy'),
            apt_repo(trusted=True),
            apt_repo(trusted='yes'),
            {k: v for k, v in apt_repo().items() if k != 'key_url'},
        ],
    )
    def test_validate_rejects_invalid_repo(self, repo):
        with pytest.raises(ValueError):
            deb._validate_apt_repos([repo])

    def test_validate_rejects_duplicate_names(self):
        with pytest.raises(ValueError):
            deb._validate_apt_repos([apt_repo(), apt_repo()])

    @patch("teuthology.task.install.deb._get_builder_project")
    @patch("teuthology.task.install.deb._ensure_release_key")
    def test_install_with_custom_repos(self, m_key, m_builder):
        remote = Mock()
        config = dict(
            repos=[apt_repo()],
            extra_system_packages=dict(deb=['sys1']),
        )
        deb._update_package_list_and_install(
            Mock(), remote, ['pkg1', 'pkg2'], config)

        m_builder.assert_not_called()
        m_key.assert_not_called()
        key_path = '/etc/apt/keyrings/teuthology-custom.asc'
        remote.sudo_write_file.assert_called_once_with(
            '/etc/apt/sources.list.d/teuthology-custom.list',
            'deb [signed-by=%s] https://example.com/ubuntu jammy main\n'
            % key_path,
            mode='0644',
        )
        calls = [c[1]['args'] for c in remote.run.call_args_list]
        fetch_key = ['sudo', 'curl', '-sSfL', '-o', key_path,
                     'https://example.com/release.asc']
        update = ['sudo', 'apt-get', 'update']
        assert calls.index(fetch_key) < calls.index(update)
        assert remote.run.call_args_list[calls.index(update)][1][
            'check_status'] is True
        installs = [c for c in calls if 'install' in c and 'apt-get' in c]
        assert [c[-2:] for c in installs[:1]] == [['pkg1', 'pkg2']]
        assert installs[1][-1] == 'sys1'

    @patch("teuthology.task.install.deb._get_builder_project")
    def test_install_with_trusted_repo(self, m_builder):
        remote = Mock()
        repo = {k: v for k, v in apt_repo().items() if k != 'key_url'}
        repo['trusted'] = True
        deb._update_package_list_and_install(
            Mock(), remote, ['pkg1'], dict(repos=[repo]))

        remote.sudo_write_file.assert_called_once_with(
            '/etc/apt/sources.list.d/teuthology-custom.list',
            'deb [trusted=yes] https://example.com/ubuntu jammy main\n',
            mode='0644',
        )
        calls = [c[1]['args'] for c in remote.run.call_args_list]
        assert not any('curl' in c for c in calls)

    @patch("teuthology.task.install.deb._get_builder_project")
    def test_install_with_flat_repo(self, m_builder):
        remote = Mock()
        repo = apt_repo(suite='./', trusted=True)
        del repo['components'], repo['key_url']
        deb._update_package_list_and_install(
            Mock(), remote, ['pkg1'], dict(repos=[repo]))

        remote.sudo_write_file.assert_called_once_with(
            '/etc/apt/sources.list.d/teuthology-custom.list',
            'deb [trusted=yes] https://example.com/ubuntu ./\n',
            mode='0644',
        )

    @patch("teuthology.task.install.deb._get_builder_project")
    @patch("teuthology.task.install.deb._ensure_release_key")
    def test_install_without_repos_uses_builder(self, m_key, m_builder):
        builder = m_builder.return_value
        builder.version = '1.2.3'
        remote = Mock()
        deb._update_package_list_and_install(Mock(), remote, ['pkg1'], {})

        m_key.assert_called_once_with(remote)
        builder.install_repo.assert_called_once_with()
        remote.sudo_write_file.assert_not_called()
        install = remote.run.call_args_list[-1][1]['args']
        assert install[-1] == 'pkg1=1.2.3'

    @patch("teuthology.task.install.deb._get_builder_project")
    def test_invalid_repos_do_not_touch_remote(self, m_builder):
        remote = Mock()
        with pytest.raises(ValueError):
            deb._update_package_list_and_install(
                Mock(), remote, ['pkg1'], dict(repos=[apt_repo(priority=1)]))
        remote.run.assert_not_called()
        remote.sudo_write_file.assert_not_called()

    @patch("teuthology.task.install.deb._get_builder_project")
    def test_remove_sources_list_only_removes_generated_files(self, m_builder):
        remote = Mock()
        config = dict(repos=[apt_repo(name='a'), apt_repo(name='b')])
        deb._remove_sources_list(Mock(), config, remote)

        m_builder.assert_not_called()
        assert remote.run.call_args_list[0][1]['args'] == [
            'sudo', 'rm', '-f',
            '/etc/apt/sources.list.d/teuthology-a.list',
            '/etc/apt/keyrings/teuthology-a.asc',
            '/etc/apt/sources.list.d/teuthology-b.list',
            '/etc/apt/keyrings/teuthology-b.asc',
        ]

    @pytest.mark.parametrize(
        'task_config, overrides, expect',
        [
            ({'repos': [apt_repo(name='task')]}, {}, 'task'),
            ({'repos': [apt_repo(name='task')]},
             {'repos': [apt_repo(name='override')]}, 'override'),
            ({}, {}, None),
        ],
    )
    @patch("teuthology.task.install.ship_utilities")
    @patch("teuthology.task.install.install")
    def test_task_passes_repos_to_install(self, m_install, m_ship,
                                          task_config, overrides, expect):
        m_install.side_effect = lambda ctx, config: contextlib.nullcontext()
        m_ship.side_effect = lambda ctx, config: contextlib.nullcontext()
        ctx = Mock(config={'overrides': {'install': overrides}}, summary={})
        with install.task(ctx, task_config):
            pass
        nested_config = m_install.call_args[1]['config']
        if expect is None:
            assert 'repos' not in nested_config
        else:
            assert nested_config['repos'][0]['name'] == expect

    @patch("teuthology.task.install.deb._get_builder_project")
    @patch("teuthology.task.install.deb._ensure_release_key")
    def test_install_with_version_pins_project_packages(self, m_key,
                                                        m_builder):
        remote = Mock()
        config = dict(
            repos=[apt_repo()],
            version='20.2.5-2',
            extra_system_packages=dict(deb=['sys1', 'sys2']),
        )
        deb._update_package_list_and_install(
            Mock(), remote, ['ceph', 'ceph-common'], config)

        m_builder.assert_not_called()
        calls = [c[1]['args'] for c in remote.run.call_args_list]
        installs = [c for c in calls if 'install' in c and 'apt-get' in c]
        assert installs[0][-2:] == ['ceph=20.2.5-2', 'ceph-common=20.2.5-2']
        assert 'ceph' not in installs[0]
        assert 'ceph-common' not in installs[0]
        assert installs[1][-2:] == ['sys1', 'sys2']

    @pytest.mark.parametrize('version', [None, '', ' 1.0', '1.0 2', 20.2, 3])
    @patch("teuthology.task.install.deb._get_builder_project")
    def test_invalid_version_does_not_touch_remote(self, m_builder, version):
        remote = Mock()
        config = dict(repos=[apt_repo()], version=version)
        with pytest.raises(ValueError):
            deb._update_package_list_and_install(
                Mock(), remote, ['ceph'], config)
        remote.run.assert_not_called()
        remote.sudo_write_file.assert_not_called()

    @patch("teuthology.task.install.deb._get_builder_project")
    @patch("teuthology.task.install.deb._ensure_release_key")
    def test_upgrade_with_repos_is_not_supported(self, m_key, m_builder):
        remote = Mock()
        config = dict(repos=[apt_repo()])
        with pytest.raises(ValueError):
            deb._upgrade_packages(Mock(), config, remote, ['ceph'])
        m_key.assert_not_called()
        m_builder.assert_not_called()
        remote.run.assert_not_called()

    @pytest.mark.parametrize(
        'task_config, overrides',
        [
            ({'version': '1.0'}, {}),
            ({}, {'version': '1.0'}),
            ({'version': ''}, {}),
        ],
    )
    @patch("teuthology.task.install.ship_utilities")
    @patch("teuthology.task.install.install")
    def test_task_rejects_version_without_repos(self, m_install, m_ship,
                                                task_config, overrides):
        ctx = Mock(config={'overrides': {'install': overrides}}, summary={})
        with pytest.raises(ValueError):
            with install.task(ctx, task_config):
                pass
        m_install.assert_not_called()

    @pytest.mark.parametrize(
        'task_config, overrides, expect',
        [
            ({'repos': [apt_repo()], 'version': '1.0'}, {}, '1.0'),
            ({'repos': [apt_repo()], 'version': '1.0'},
             {'version': '2.0'}, '2.0'),
            ({'repos': [apt_repo()]}, {'version': '2.0'}, '2.0'),
            ({'repos': [apt_repo()]}, {}, None),
        ],
    )
    @patch("teuthology.task.install.ship_utilities")
    @patch("teuthology.task.install.install")
    def test_task_passes_version_to_install(self, m_install, m_ship,
                                            task_config, overrides, expect):
        m_install.side_effect = lambda ctx, config: contextlib.nullcontext()
        m_ship.side_effect = lambda ctx, config: contextlib.nullcontext()
        ctx = Mock(config={'overrides': {'install': overrides}}, summary={})
        with install.task(ctx, task_config):
            pass
        nested_config = m_install.call_args[1]['config']
        if expect is None:
            assert 'version' not in nested_config
        else:
            assert nested_config['version'] == expect
