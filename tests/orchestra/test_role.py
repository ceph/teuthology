import pytest

from teuthology.orchestra.role import Role


def test_iter_name_index():
    expected = [
        (['client.0', 'osd.0', 'ceph.osd.1'], 'osd', ['0', '1']),
        (['client.0', 'osd.0', 'ceph.osd.1'], 'client', ['0']),
        (['foo.client.1', 'bar.client.2.3', 'baz.osd.1'], 'mon', []),
        (['foo.client.1', 'bar.client.2.3', 'baz.osd.1'], 'client',
         ['1', '2.3']),
        ]
    for target_roles, name, expected_idxs in expected:
        idxs = list(i for (_, i) in Role.iter_name_index(target_roles, name))
        assert idxs == expected_idxs


def test_iter_roles():
    expected = [
        (['client.0', 'osd.0', 'ceph.osd.1'], 'osd', 'ceph',
         ['osd.0', 'ceph.osd.1']),
        (['client.0', 'osd.0', 'ceph.osd.1'], 'client', 'ceph',
         ['client.0']),
        (['foo.client.1', 'bar.client.2.3', 'baz.osd.1'], 'mon', None, []),
        (['foo.client.1', 'bar.client.2.3', 'baz.osd.1'], 'client', None,
         ['foo.client.1', 'bar.client.2.3']),
        (['foo.client.1', 'bar.client.2.3', 'baz.osd.1'], 'client', 'bar',
         ['bar.client.2.3']),
        ]
    for target_roles, role_name, cluster_name, expected_roles in expected:
        roles = list(Role.iter_roles(target_roles, role_name, cluster_name))
        assert roles == expected_roles


def test_matcher():
    is_client = Role.make_matcher('client')
    assert is_client('client.0')
    assert is_client('ceph.client.0')
    assert is_client('foo.client.0')
    assert is_client('foo.client.bar.baz')

    with pytest.raises(ValueError):
        is_client('')
        is_client('client')
    assert not is_client('foo.bar.baz')
    assert not is_client('ceph.client')
    assert not is_client('hadoop.main.0')


def test_matcher_in_cluster():
    is_c1_osd = Role.make_matcher('osd', 'c1')
    with pytest.raises(ValueError):
        is_c1_osd('')
    assert not is_c1_osd('osd.0')
    assert not is_c1_osd('ceph.osd.0')
    assert not is_c1_osd('ceph.osd.0')
    assert not is_c1_osd('c11.osd.0')
    assert is_c1_osd('c1.osd.0')
    assert is_c1_osd('c1.osd.999')


def test_as_tuple():
    expected = {
        'client.0': ('ceph', 'client', '0'),
        'foo.client.0': ('foo', 'client', '0'),
        'bar.baz.x.y.z': ('bar', 'baz', 'x.y.z'),
        'mds.a-s-b': ('ceph', 'mds', 'a-s-b'),
    }

    for role, expected_split in expected.items():
        actual_split = Role.as_tuple(role)
        assert actual_split == expected_split
