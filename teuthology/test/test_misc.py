import argparse
from datetime import datetime

from mock import Mock, patch
from teuthology.orchestra import cluster
from teuthology.config import config
from teuthology import misc
import subprocess

import pytest


class FakeRemote(object):
    pass


def test_sh_normal(caplog):
    assert misc.sh("/bin/echo ABC") == "ABC\n"
    assert "truncated" not in caplog.text


def test_sh_truncate(caplog):
    assert misc.sh("/bin/echo -n AB ; /bin/echo C", 2) == "ABC\n"
    assert "truncated" in caplog.text
    assert "ABC" not in caplog.text


def test_sh_fail(caplog):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        misc.sh("/bin/echo -n AB ; /bin/echo C ; exit 111", 2) == "ABC\n"
    assert excinfo.value.returncode == 111
    for record in caplog.records:
        if record.levelname == 'ERROR':
            assert ('replay full' in record.message or
                    'ABC\n' == record.message)

def test_sh_progress(caplog):
    misc.sh("echo AB ; sleep 5 ; /bin/echo C", 2) == "ABC\n"
    records = caplog.records
    assert ':sh: ' in records[0].message
    assert 'AB' == records[1].message
    assert 'C' == records[2].message
    #
    # With a sleep 5 between the first and the second message,
    # there must be at least 2 seconds between the log record
    # of the first message and the log record of the second one
    #
    t1 = datetime.strptime(records[1].asctime.split(',')[0], "%Y-%m-%d %H:%M:%S")
    t2 = datetime.strptime(records[2].asctime.split(',')[0], "%Y-%m-%d %H:%M:%S")
    assert (t2 - t1).total_seconds() > 2


def test_wait_until_osds_up():
    ctx = argparse.Namespace()
    ctx.daemons = Mock()
    ctx.daemons.iter_daemons_of_role.return_value = list()
    remote = FakeRemote()

    def s(self, **kwargs):
        return 'IGNORED\n{"osds":[{"state":["up"]}]}'

    remote.sh = s
    ctx.cluster = cluster.Cluster(
        remotes=[
            (remote, ['osd.0', 'client.1'])
        ],
    )
    with patch.multiple(
            misc,
            get_testdir=lambda ctx: "TESTDIR",
    ):
        misc.wait_until_osds_up(ctx, ctx.cluster, remote)


def test_get_clients_simple():
    ctx = argparse.Namespace()
    remote = FakeRemote()
    ctx.cluster = cluster.Cluster(
        remotes=[
            (remote, ['client.0', 'client.1'])
        ],
    )
    g = misc.get_clients(ctx=ctx, roles=['client.1'])
    got = next(g)
    assert len(got) == 2
    assert got[0] == ('1')
    assert got[1] is remote
    with pytest.raises(StopIteration):
        next(g)


def test_get_mon_names():
    expected = [
        ([['mon.a', 'osd.0', 'mon.c']], 'ceph', ['mon.a', 'mon.c']),
        ([['ceph.mon.a', 'osd.0', 'ceph.mon.c']], 'ceph', ['ceph.mon.a', 'ceph.mon.c']),
        ([['mon.a', 'osd.0', 'mon.c'], ['ceph.mon.b']], 'ceph', ['mon.a', 'mon.c', 'ceph.mon.b']),
        ([['mon.a', 'osd.0', 'mon.c'], ['foo.mon.a']], 'ceph', ['mon.a', 'mon.c']),
        ([['mon.a', 'osd.0', 'mon.c'], ['foo.mon.a']], 'foo', ['foo.mon.a']),
    ]
    for remote_roles, cluster_name, expected_mons in expected:
        ctx = argparse.Namespace()
        ctx.cluster = Mock()
        ctx.cluster.remotes = {i: roles for i, roles in enumerate(remote_roles)}
        mons = misc.get_mon_names(ctx, cluster_name)
        assert expected_mons == mons


def test_get_first_mon():
    expected = [
        ([['mon.a', 'osd.0', 'mon.c']], 'ceph', 'mon.a'),
        ([['ceph.mon.a', 'osd.0', 'ceph.mon.c']], 'ceph', 'ceph.mon.a'),
        ([['mon.a', 'osd.0', 'mon.c'], ['ceph.mon.b']], 'ceph', 'ceph.mon.b'),
        ([['mon.a', 'osd.0', 'mon.c'], ['foo.mon.a']], 'ceph', 'mon.a'),
        ([['foo.mon.b', 'osd.0', 'mon.c'], ['foo.mon.a']], 'foo', 'foo.mon.a'),
    ]
    for remote_roles, cluster_name, expected_mon in expected:
        ctx = argparse.Namespace()
        ctx.cluster = Mock()
        ctx.cluster.remotes = {i: roles for i, roles in enumerate(remote_roles)}
        mon = misc.get_first_mon(ctx, None, cluster_name)
        assert expected_mon == mon


def test_roles_of_type():
    expected = [
        (['client.0', 'osd.0', 'ceph.osd.1'], 'osd', ['0', '1']),
        (['client.0', 'osd.0', 'ceph.osd.1'], 'client', ['0']),
        (['foo.client.1', 'bar.client.2.3', 'baz.osd.1'], 'mon', []),
        (['foo.client.1', 'bar.client.2.3', 'baz.osd.1'], 'client',
         ['1', '2.3']),
        ]
    for roles_for_host, type_, expected_ids in expected:
        ids = list(misc.roles_of_type(roles_for_host, type_))
        assert ids == expected_ids


def test_cluster_roles_of_type():
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
    for roles_for_host, type_, cluster_, expected_roles in expected:
        roles = list(misc.cluster_roles_of_type(roles_for_host, type_, cluster_))
        assert roles == expected_roles


def test_all_roles_of_type():
    expected = [
        ([['client.0', 'osd.0', 'ceph.osd.1'], ['bar.osd.2']],
         'osd', ['0', '1', '2']),
        ([['client.0', 'osd.0', 'ceph.osd.1'], ['bar.osd.2', 'baz.client.1']],
         'client', ['0', '1']),
        ([['foo.client.1', 'bar.client.2.3'], ['baz.osd.1']], 'mon', []),
        ([['foo.client.1', 'bar.client.2.3'], ['baz.osd.1', 'ceph.client.bar']],
         'client', ['1', '2.3', 'bar']),
        ]
    for host_roles, type_, expected_ids in expected:
        cluster_ = Mock()
        cluster_.remotes = dict(enumerate(host_roles))
        ids = list(misc.all_roles_of_type(cluster_, type_))
        assert ids == expected_ids


def test_get_http_log_path():
    # Fake configuration
    archive_server = "http://example.com/server_root"
    config.archive_server = archive_server
    archive_dir = "/var/www/archives"

    path = misc.get_http_log_path(archive_dir)
    assert path == "http://example.com/server_root/archives/"

    job_id = '12345'
    path = misc.get_http_log_path(archive_dir, job_id)
    assert path == "http://example.com/server_root/archives/12345/"

    # Inktank configuration
    archive_server = "http://qa-proxy.ceph.com/teuthology/"
    config.archive_server = archive_server
    archive_dir = "/var/lib/teuthworker/archive/teuthology-2013-09-12_11:49:50-ceph-deploy-master-testing-basic-vps"
    job_id = 31087
    path = misc.get_http_log_path(archive_dir, job_id)
    assert path == "http://qa-proxy.ceph.com/teuthology/teuthology-2013-09-12_11:49:50-ceph-deploy-master-testing-basic-vps/31087/"

    path = misc.get_http_log_path(archive_dir)
    assert path == "http://qa-proxy.ceph.com/teuthology/teuthology-2013-09-12_11:49:50-ceph-deploy-master-testing-basic-vps/"


def test_is_type():
    is_client = misc.is_type('client')
    assert is_client('client.0')
    assert is_client('ceph.client.0')
    assert is_client('foo.client.0')
    assert is_client('foo.client.bar.baz')

    with pytest.raises(ValueError):
        is_client('')
        is_client('client')
    assert not is_client('foo.bar.baz')
    assert not is_client('ceph.client')
    assert not is_client('hadoop.master.0')


def test_is_type_in_cluster():
    is_c1_osd = misc.is_type('osd', 'c1')
    with pytest.raises(ValueError):
        is_c1_osd('')
    assert not is_c1_osd('osd.0')
    assert not is_c1_osd('ceph.osd.0')
    assert not is_c1_osd('ceph.osd.0')
    assert not is_c1_osd('c11.osd.0')
    assert is_c1_osd('c1.osd.0')
    assert is_c1_osd('c1.osd.999')


def test_get_mons():
    ips = ['1.1.1.1', '2.2.2.2', '3.3.3.3']
    addrs = ['1.1.1.1:6789', '1.1.1.1:6790', '1.1.1.1:6791']

    mons = misc.get_mons([['mon.a']], ips)
    assert mons == {'mon.a': addrs[0]}

    mons = misc.get_mons([['cluster-a.mon.foo', 'client.b'], ['osd.0']], ips)
    assert mons == {'cluster-a.mon.foo': addrs[0]}

    mons = misc.get_mons([['mon.a', 'mon.b', 'ceph.mon.c']], ips)
    assert mons == {'mon.a': addrs[0],
                    'mon.b': addrs[1],
                    'ceph.mon.c': addrs[2]}

    mons = misc.get_mons([['mon.a'], ['mon.b'], ['ceph.mon.c']], ips)
    assert mons == {'mon.a': addrs[0],
                    'mon.b': ips[1] + ':6789',
                    'ceph.mon.c': ips[2] + ':6789'}


def test_split_role():
    expected = {
        'client.0': ('ceph', 'client', '0'),
        'foo.client.0': ('foo', 'client', '0'),
        'bar.baz.x.y.z': ('bar', 'baz', 'x.y.z'),
        'mds.a-s-b': ('ceph', 'mds', 'a-s-b'),
    }

    for role, expected_split in expected.items():
        actual_split = misc.split_role(role)
        assert actual_split == expected_split

class TestHostnames(object):
    def setup(self):
        config._conf = dict()

    def teardown(self):
        config.load()

    def test_canonicalize_hostname(self):
        host_base = 'box1'
        result = misc.canonicalize_hostname(host_base)
        assert result == 'ubuntu@box1.front.sepia.ceph.com'

    def test_decanonicalize_hostname(self):
        host = 'ubuntu@box1.front.sepia.ceph.com'
        result = misc.decanonicalize_hostname(host)
        assert result == 'box1'

    def test_canonicalize_hostname_nouser(self):
        host_base = 'box1'
        result = misc.canonicalize_hostname(host_base, user=None)
        assert result == 'box1.front.sepia.ceph.com'

    def test_decanonicalize_hostname_nouser(self):
        host = 'box1.front.sepia.ceph.com'
        result = misc.decanonicalize_hostname(host)
        assert result == 'box1'

    def test_canonicalize_hostname_otherlab(self):
        config.lab_domain = 'example.com'
        host_base = 'box1'
        result = misc.canonicalize_hostname(host_base)
        assert result == 'ubuntu@box1.example.com'

    def test_decanonicalize_hostname_otherlab(self):
        config.lab_domain = 'example.com'
        host = 'ubuntu@box1.example.com'
        result = misc.decanonicalize_hostname(host)
        assert result == 'box1'


class TestMergeConfigs(object):
    """ Tests merge_config and deep_merge in teuthology.misc """

    @patch("os.path.exists")
    @patch("yaml.safe_load")
    @patch("__builtin__.open")
    def test_merge_configs(self, m_open, m_safe_load, m_exists):
        """ Only tests with one yaml file being passed, mainly just to test
            the loop logic.  The actual merge will be tested in subsequent
            tests.
        """
        expected = {"a": "b", "b": "c"}
        m_exists.return_value = True
        m_safe_load.return_value = expected
        result = misc.merge_configs(["path/to/config1"])
        assert result == expected
        m_open.assert_called_once_with("path/to/config1")

    def test_merge_configs_empty(self):
        assert misc.merge_configs([]) == {}

    def test_deep_merge(self):
        a = {"a": "b"}
        b = {"b": "c"}
        result = misc.deep_merge(a, b)
        assert result == {"a": "b", "b": "c"}

    def test_overwrite_deep_merge(self):
        a = {"a": "b"}
        b = {"a": "overwritten", "b": "c"}
        result = misc.deep_merge(a, b)
        assert result == {"a": "overwritten", "b": "c"}

    def test_list_deep_merge(self):
        a = [1, 2]
        b = [3, 4]
        result = misc.deep_merge(a, b)
        assert result == [1, 2, 3, 4]

    def test_missing_list_deep_merge(self):
        a = [1, 2]
        b = "not a list"
        with pytest.raises(AssertionError):
            misc.deep_merge(a, b)

    def test_missing_a_deep_merge(self):
        result = misc.deep_merge(None, [1, 2])
        assert result == [1, 2]

    def test_missing_b_deep_merge(self):
        result = misc.deep_merge([1, 2], None)
        assert result == [1, 2]

    def test_invalid_b_deep_merge(self):
        with pytest.raises(AssertionError):
            misc.deep_merge({"a": "b"}, "invalid")


class TestIsInDict(object):
    def test_simple_membership(self):
        assert misc.is_in_dict('a', 'foo', {'a':'foo', 'b':'bar'})

    def test_dict_membership(self):
        assert misc.is_in_dict(
            'a', {'sub1':'key1', 'sub2':'key2'},
            {'a':{'sub1':'key1', 'sub2':'key2', 'sub3':'key3'}}
        )

    def test_simple_nonmembership(self):
        assert not misc.is_in_dict('a', 'foo', {'a':'bar', 'b':'foo'})

    def test_nonmembership_with_presence_at_lower_level(self):
        assert not misc.is_in_dict('a', 'foo', {'a':{'a': 'foo'}})
