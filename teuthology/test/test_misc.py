import argparse
from datetime import datetime

from mock import patch
from ..orchestra import cluster
from .. import misc
from ..config import config
import subprocess

import pytest


class FakeRemote(object):
    pass


def test_sh_normal(caplog):
    assert misc.sh("/bin/echo ABC") == "ABC\n"
    assert "truncated" not in caplog.text()


def test_sh_truncate(caplog):
    assert misc.sh("/bin/echo -n AB ; /bin/echo C", 2) == "ABC\n"
    assert "truncated" in caplog.text()
    assert "ABC" not in caplog.text()


def test_sh_fail(caplog):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        misc.sh("/bin/echo -n AB ; /bin/echo C ; exit 111", 2) == "ABC\n"
    assert excinfo.value.returncode == 111
    for record in caplog.records():
        if record.levelname == 'ERROR':
            assert ('replay full' in record.message or
                    'ABC\n' == record.message)

def test_sh_progress(caplog):
    misc.sh("echo AB ; sleep 5 ; /bin/echo C", 2) == "ABC\n"
    records = caplog.records()
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


def test_get_block_devices():
    remote = FakeRemote()
    PASS_1 = PROC_PARTITIONS, BLOCK_DEVICES
    PASS_2 = MIRA_PROC_PARTITIONS, MIRA_BLOCK_DEVICES
    PASS_3 = BIG_PROC_PARTITIONS, BIG_BLOCK_DEVICES

    for current_pass in PASS_1, PASS_2, PASS_3:
        class r():
            class o:
                def getvalue(self):
                    return current_pass[0]
            stdout = o()

        remote.run = lambda **kwargs: r()

        devices = misc.get_block_devices(remote)
        assert devices == current_pass[1]


def test_get_used_block_devices():
    remote = FakeRemote()
    PASS_1 = PROC_MOUNTS, USED_DEVICES
    PASS_2 = PROC_MOUNTS_MIRA, USED_DEVICES_MIRA

    for current_pass in PASS_1, PASS_2:
        class r():
            class o:
                def getvalue(self):
                    return current_pass[0]
            stdout = o()

        remote.run = lambda **kwargs: r()
        devices = misc.get_used_block_devices(remote)
        assert devices == current_pass[1]


def test_translate_block_device_path():
    remote = FakeRemote()
    PASS_1 = USED_DEVICES_WITH_BLOCK, READLINK
    PASS_2 = USED_DEVICES_MIRA, READLINK_MIRA
    for current_pass in PASS_1, PASS_2:
        for device in current_pass[0]:
            class r():
                class o:
                    def getvalue(self):
                        return current_pass[1][device]
                stdout = o()

            remote.run = lambda **kwargs: r()
            assert misc.translate_block_device_path(remote, device) == current_pass[1][device]


def test_expand_dm_devices():
    remote = FakeRemote()

    class r():
        class o:
            def getvalue(self):
                return DMSETUP
        stdout = o()

    remote.run = lambda **kwargs: r()
    assert misc.expand_dm_devices(remote, TRANSLATED_USED_DEVICES) == EXPANDED_USED_DEVICES


def test_get_root_device():
    remote = FakeRemote()

    class r():
        class o:
            def getvalue(self):
                return PROC_CMDLINE
        stdout = o()

    remote.run = lambda **kwargs: r()
    assert misc.get_root_device(remote) == ROOT_DEVICE_UUID


def test_translate_block_UUID():
    remote = FakeRemote()
    PASS_1 = BLKID, COMBINED_USED_DEVICES, NO_UUID_ROOT_DEVICE
    PASS_2 = BLKID_MIRA, COMBINED_USED_DEVICES_MIRA, NO_UUID_ROOT_DEVICE_MIRA
    for PASS in PASS_1, PASS_2, :
        class r():
            class o:
                def getvalue(self):
                    return PASS[0]
            stdout = o()

        remote.run = lambda **kwargs: r()
        assert misc.translate_block_UUID(remote, PASS[1]) == PASS[2]


def test_wait_until_osds_up():
    ctx = argparse.Namespace()
    remote = FakeRemote()

    class r():
        class o:
            def getvalue(self):
                return 'IGNORED\n{"osds":[{"state":["up"]}]}'
        stdout = o()

    remote.run = lambda **kwargs: r()
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
    @patch("__builtin__.file")
    def test_merge_configs(self, m_file, m_safe_load, m_exists):
        """ Only tests with one yaml file being passed, mainly just to test
            the loop logic.  The actual merge will be tested in subsequent
            tests.
        """
        expected = {"a": "b", "b": "c"}
        m_exists.return_value = True
        m_safe_load.return_value = expected
        result = misc.merge_configs(["path/to/config1"])
        assert result == expected
        m_file.assert_called_once_with("path/to/config1")

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

PROC_PARTITIONS = '''
major minor  #blocks  name

   8        0  500107608 sda
   8        1     204800 sda1
   8        2  314574848 sda2
   8        3   16777216 sda3
   8        4          1 sda4
   8        5  168548352 sda5
  11        0    1048575 sr0
 253        0  168546304 dm-0
'''
BLOCK_DEVICES = ['sda', 'dm-0']

BIG_PROC_PARTITIONS = '''
major minor  #blocks  name

   8     0   17774160 sda
   8     1    1052226 sda1
   8     2     208845 sda2
   8     3   10490445 sda3
   8    16     976576 sdb
   8    32     976576 sdc
   8    48     976576 sdd
   8    64     976576 sde
   8    80     976576 sdf
   8    96     976576 sdg
   8   112     976576 sdh
   8   128     976576 sdi
   8   144     976576 sdj
   8   160     976576 sdk
   8   176     976576 sdl
   8   192     976576 sdm
   8   208     976576 sdn
   8   224     976576 sdo
   8   240     976576 sdp
  65     0     976576 sdq
  65    16    1048576 sdr
  65    32    1048576 sds
  65    48    1048576 sdt
  65    64    1048576 sdu
  65    80    1048576 sdv
  65    96    1048576 sdw
  65   112    1048576 sdx
  65   128    1048576 sdy
  65   144    1048576 sdz
  65   160    1048576 sdaa
  65   176    1048576 sdab
  65   192    1048576 sdac
  65   208    1048576 sdad
  65   224    1048576 sdae
  65   240    1048576 sdaf
  66     0    1048576 sdag
  66    16    1048576 sdah
  66    32    1048576 sdai
  66    48    1048576 sdaj
  66    64    1048576 sdak
  66    80    1048576 sdal
  66    96    1048576 sdam
  66   112    1048576 sdan
  66   128    1048576 sdao
  66   144    1048576 sdap
  66   160    1048576 sdaq
  66   176    1048576 sdar
  66   192    1048576 sdas
  66   208    1048576 sdat
  66   224    1048576 sdau
  66   240    1048576 sdav
'''

BIG_BLOCK_DEVICES = ['sda','sdb','sdc','sdd','sde','sdf','sdg','sdh','sdi','sdj','sdk','sdl','sdm','sdn','sdo','sdp',
'sdq','sdr','sds','sdt','sdu','sdv','sdw','sdx','sdy','sdz', 'sdaa','sdab','sdac','sdad','sdae','sdaf','sdag','sdah',
'sdai','sdaj','sdak','sdal','sdam','sdan','sdao','sdap','sdaq','sdar','sdas','sdat','sdau','sdav']


MIRA_PROC_PARTITIONS = '''
major minor  #blocks  name

   1        0      65536 ram0
   1        1      65536 ram1
   1        2      65536 ram2
   1        3      65536 ram3
   1        4      65536 ram4
   1        5      65536 ram5
   1        6      65536 ram6
   1        7      65536 ram7
   1        8      65536 ram8
   1        9      65536 ram9
   1       10      65536 ram10
   1       11      65536 ram11
   1       12      65536 ram12
   1       13      65536 ram13
   1       14      65536 ram14
   1       15      65536 ram15
   8       16  976762584 sdb
   8       17  976751303 sdb1
   8       19      10240 sdb3
   8       32  976762584 sdc
   8       33    5242880 sdc1
   8       48  976762584 sdd
   8       64  976762584 sde
   8       65  971518663 sde1
   8       66    5241856 sde2
   8       80  976762584 sdf
   8       96  976762584 sdg
   8      112  976762584 sdh
   8        0  976762584 sda
   8        1  976760832 sda1
'''

MIRA_BLOCK_DEVICES = ['sdb', 'sdc', 'sdd', 'sde', 'sdf', 'sdg', 'sdh', 'sda']

PROC_MOUNTS = '''
/dev/mapper/luks-daddc2c4-1463-4d46-abc7-b15770b79f94 / btrfs rw,seclabel,relatime,ssd,space_cache,subvolid=257,subvol=/root 0 0
/dev/sda1 /boot ext4 rw,seclabel,relatime,data=ordered 0 0
/dev/sda2 /build btrfs rw,seclabel,relatime,ssd,space_cache,subvolid=257,subvol=/build 0 0
'''

PROC_MOUNTS_MIRA = '''
/dev/disk/by-uuid/df552b84-1070-47da-aec3-946873ebdfba / ext4 rw,relatime,errors=remount-ro,data=ordered 0 0
'''

USED_DEVICES = ['/dev/mapper/luks-daddc2c4-1463-4d46-abc7-b15770b79f94', '/dev/sda1', '/dev/sda2']
USED_DEVICES_WITH_BLOCK = ['/dev/block/8:1', '/dev/mapper/luks-daddc2c4-1463-4d46-abc7-b15770b79f94', '/dev/sda1', '/dev/sda2']
USED_DEVICES_MIRA = ['/dev/disk/by-uuid/df552b84-1070-47da-aec3-946873ebdfba']

READLINK = {'/dev/block/8:1': '/dev/sda1',
            '/dev/mapper/luks-daddc2c4-1463-4d46-abc7-b15770b79f94': '/dev/dm-0',
            '/dev/sda1': '/dev/sda1',
            '/dev/sda2': '/dev/sda2'}

READLINK_MIRA = {'/dev/disk/by-uuid/df552b84-1070-47da-aec3-946873ebdfba': '/dev/sda1'}

TRANSLATED_USED_DEVICES = ['/dev/dm-0', '/dev/sda1', '/dev/sda2']
TRANSLATED_USED_DEVICES_MIRA = ['/dev/sda1']

DMSETUP = '''
luks-daddc2c4-1463-4d46-abc7-b15770b79f94 <dm-0> (253:0)
 - <sda5> (8:5)
luks-daddc2c4-2345-2345-acb1-b15770b79fff <dm-1> (253:1)
 - <sdb5> (8:10)
'''

EXPANDED_USED_DEVICES = ['/dev/sda5', '/dev/sda1', '/dev/sda2']

PROC_CMDLINE = '''
BOOT_IMAGE=/vmlinuz-4.4.6-300.fc23.x86_64 root=UUID=4945724f-27de-48e3-937f-c767f92e86a6 ro rootflags=subvol=root rd.luks.uuid=luks-daddc2c4-1463-4d46-abc7-b15770b79f94 rhgb quiet LANG=fr_FR.UTF-8 "acpi_osi=!Windows 2013" nouveau.runpm=0 intel_iommu=on
'''

ROOT_DEVICE_UUID = '''UUID=4945724f-27de-48e3-937f-c767f92e86a6'''
COMBINED_USED_DEVICES = ['/dev/sda1', 'UUID=4945724f-27de-48e3-937f-c767f92e86a6']
COMBINED_USED_DEVICES_MIRA = ['/dev/sda1', 'UUID=df552b84-1070-47da-aec3-946873ebdfba']

BLKID = '''
/dev/sda2: LABEL="buildgroup" UUID="c3d3ae17-1ece-432e-bb4b-f38bfa12e876" UUID_SUB="dd2b2031-6c8a-4f46-8f59-27153376e90d" TYPE="btrfs" PARTUUID="ee3a7940-02"
/dev/sda3: UUID="51f0126d-0d7f-4708-b8b8-f122ac8dcf46" TYPE="swap" PARTUUID="ee3a7940-03"
/dev/sda5: UUID="daddc2c4-1463-4d46-abc7-b15770b79f94" TYPE="crypto_LUKS" PARTUUID="ee3a7940-05"
/dev/block/8:5: UUID="daddc2c4-1463-4d46-abc7-b15770b79f94" TYPE="crypto_LUKS" PARTUUID="ee3a7940-05"
/dev/block/253:0: LABEL="fedora" UUID="4945724f-27de-48e3-937f-c767f92e86a6" UUID_SUB="ee1d1234-29bc-43b0-8e4f-7bfa2aa55981" TYPE="btrfs"
/dev/block/8:1: UUID="71adc8ce-fc61-419d-82d5-0faec6d97f60" TYPE="ext4" PARTUUID="ee3a7940-01"
/dev/dm-0: LABEL="fedora" UUID="4945724f-27de-48e3-937f-c767f92e86a6" UUID_SUB="ee1d1234-29bc-43b0-8e4f-7bfa2aa55981" TYPE="btrfs"
/dev/mapper/luks-daddc2c4-1463-4d46-abc7-b15770b79f94: LABEL="fedora" UUID="4945724f-27de-48e3-937f-c767f92e86a6" UUID_SUB="ee1d1234-29bc-43b0-8e4f-7bfa2aa55981" TYPE="btrfs"
/dev/sda1: UUID="71adc8ce-fc61-419d-82d5-0faec6d97f60" TYPE="ext4" PARTUUID="ee3a7940-01"
'''

NO_UUID_ROOT_DEVICE = ['/dev/sda1', '/dev/block/253:0', '/dev/dm-0', '/dev/mapper/luks-daddc2c4-1463-4d46-abc7-b15770b79f94']

BLKID_MIRA = '''
/dev/sdb1: UUID="37e3bde1-ef3a-4649-827e-acd8552ca803" TYPE="crypto_LUKS"
/dev/sdb3: UUID="12164eb1-f0d2-4da0-b2cf-814300d4f420" TYPE="ext4"
/dev/sdc1: UUID="e8e1fbb1-3230-43e0-be0c-1bfa88971666" TYPE="crypto_LUKS"
/dev/sde1: UUID="2d61ce6d-edaf-4b29-839b-505b6c064474" TYPE="xfs"
/dev/sdf: UUID="c222eb40-6083-47ec-aefb-09f1afb217c2" UUID_SUB="3da3ba22-df27-4691-bab0-79e7e26c605b" TYPE="btrfs"
/dev/sdg: UUID="b98f1509-d729-476d-b901-d2acc760da26" UUID_SUB="c476c314-6abc-4d4b-94a4-de1a8cc007bd" TYPE="btrfs"
/dev/sdh: UUID="57f503cf-05dd-429b-9957-3cd316db2bf0" UUID_SUB="50fe83f2-1e29-4107-82c1-319f2b935371" TYPE="btrfs"
/dev/sdk1: UUID="df552b84-1070-47da-aec3-946873ebdfba" TYPE="ext4"
'''

NO_UUID_ROOT_DEVICE_MIRA = ['/dev/sda1', '/dev/sdk1']
