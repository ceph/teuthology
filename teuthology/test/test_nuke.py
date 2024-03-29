import datetime
import json
import os
import pytest
import subprocess

from unittest.mock import patch, Mock, DEFAULT, ANY

from teuthology import nuke
from teuthology import misc
from teuthology.config import config
from teuthology.dispatcher.supervisor import create_fake_context

class TestNuke(object):

    #@pytest.mark.skipif('OS_AUTH_URL' not in os.environ,
    #                    reason="no OS_AUTH_URL environment variable")
    def test_stale_openstack_volumes(self):
        ctx = Mock()
        ctx.teuthology_config = config
        ctx.dry_run = False
        now = datetime.datetime.strftime(datetime.datetime.now(),
                                         "%Y-%m-%dT%H:%M:%S.000000")
        id = '4bee3af9-febb-40c1-a17e-ff63edb415c5'
        name = 'target1-0'
        volume_list = json.loads(
            '[{'
            ' "ID": "' + id + '"'
            '}]'
        )
        #
        # A volume created a second ago is left untouched
        #
        volume_show = (
            '{"id": "' + id + '", '
            '"created_at": "' + now + '", '
            '"display_name": "' + name + '"}'
        )

        with patch('teuthology.nuke.openstack_delete_volume') as m_os_del_vol:
            with patch.object(nuke.OpenStack, 'run') as m_os_run:
                m_os_run.return_value = volume_show
                nuke.stale_openstack_volumes(ctx, volume_list)
                m_os_del_vol.assert_not_called()


        #
        # A volume created long ago is destroyed
        #
        ancient = "2000-11-02T15:43:12.000000"
        volume_show = (
            '{"id": "' + id + '", '
            '"created_at": "' + ancient + '", '
            '"display_name": "' + name + '"}'
        )

        with patch('teuthology.nuke.openstack_delete_volume') as m_os_del_vol:
            with patch.object(nuke.OpenStack, 'run') as m_os_run:
                m_os_run.return_value = volume_show
                nuke.stale_openstack_volumes(ctx, volume_list)
                m_os_del_vol.assert_called_with(id)

        #
        # A volume that no longer exists is ignored
        #
        with patch('teuthology.nuke.openstack_delete_volume') as m_os_del_vol:
            with patch.object(nuke.OpenStack, 'run') as m_os_run:
                m_os_run.side_effect = subprocess.CalledProcessError('ERROR', 'FAIL')
                nuke.stale_openstack_volumes(ctx, volume_list)
                m_os_del_vol.assert_not_called()

    def test_stale_openstack_nodes(self):
        ctx = Mock()
        ctx.teuthology_config = config
        ctx.dry_run = False
        name = 'target1'
        uuid = 'UUID1'
        now = datetime.datetime.strftime(datetime.datetime.now(),
                                         "%Y-%m-%d %H:%M:%S.%f")
        #
        # A node is not of type openstack is left untouched
        #
        with patch("teuthology.lock.ops.unlock_one") as m_unlock_one:
            nuke.stale_openstack_nodes(
                ctx,
                {},
                {name: {'locked_since': now, 'machine_type': 'mira'}},
            )
            m_unlock_one.assert_not_called()
        #
        # A node that was just locked and does not have
        # an instance yet is left untouched
        #
        with patch("teuthology.lock.ops.unlock_one") as m_unlock_one:
            nuke.stale_openstack_nodes(
                ctx,
                {},
                {name: {'locked_since': now, 'machine_type': 'openstack'}},
            )
            m_unlock_one.assert_not_called()
        #
        # A node that has been locked for some time and
        # has no instance is unlocked.
        #
        ancient = "2000-11-02 15:43:12.000000"
        me = 'loic@dachary.org'
        with patch("teuthology.lock.ops.unlock_one") as m_unlock_one:
            nuke.stale_openstack_nodes(
                ctx,
                {},
                {name: {'locked_since': ancient, 'locked_by': me, 'machine_type': 'openstack'}},
            )
            m_unlock_one.assert_called_with(ctx, name, me)
        #
        # A node that has been locked for some time and
        # has an instance is left untouched
        #
        with patch("teuthology.lock.ops.unlock_one") as m_unlock_one:
            nuke.stale_openstack_nodes(
                ctx,
                {uuid: {'ID': uuid, 'Name': name}},
                {name: {'locked_since': ancient, 'machine_type': 'openstack'}},
            )
            m_unlock_one.assert_not_called()

    def test_stale_openstack_instances(self):
        if 'OS_AUTH_URL' not in os.environ:
            pytest.skip('no OS_AUTH_URL environment variable')
        ctx = Mock()
        ctx.teuthology_config = config
        ctx.dry_run = False
        name = 'target1'
        uuid = 'UUID1'
        #
        # An instance created a second ago is left untouched,
        # even when it is not locked.
        #
        with patch.multiple(
                nuke.OpenStackInstance,
                exists=lambda _: True,
                get_created=lambda _: 1,
                __getitem__=lambda _, key: name,
                destroy=DEFAULT,
                ) as m:
            nuke.stale_openstack_instances(ctx, {
                uuid: { 'Name': name, },
            }, {
            })
            m['destroy'].assert_not_called()
        #
        # An instance created a very long time ago is destroyed
        #
        with patch.multiple(
                nuke.OpenStackInstance,
                exists=lambda _: True,
                get_created=lambda _: 1000000000,
                __getitem__=lambda _, key: name,
                destroy=DEFAULT,
                ) as m:
            nuke.stale_openstack_instances(ctx, {
                uuid: { 'Name': name, },
            }, {
                misc.canonicalize_hostname(name, user=None): {},
            })
            m['destroy'].assert_called_with()
        #
        # An instance that turns out to not exist any longer
        # is ignored.
        #
        with patch.multiple(
                nuke.OpenStackInstance,
                exists=lambda _: False,
                __getitem__=lambda _, key: name,
                destroy=DEFAULT,
                ) as m:
            nuke.stale_openstack_instances(ctx, {
                uuid: { 'Name': name, },
            }, {
                misc.canonicalize_hostname(name, user=None): {},
            })
            m['destroy'].assert_not_called()
        #
        # An instance created but not locked after a while is
        # destroyed.
        #
        with patch.multiple(
                nuke.OpenStackInstance,
                exists=lambda _: True,
                get_created=lambda _: nuke.OPENSTACK_DELAY + 1,
                __getitem__=lambda _, key: name,
                destroy=DEFAULT,
                ) as m:
            nuke.stale_openstack_instances(ctx, {
                uuid: { 'Name': name, },
            }, {
            })
            m['destroy'].assert_called_with()
        #
        # An instance created within the expected lifetime
        # of a job and locked is left untouched.
        #
        with patch.multiple(
                nuke.OpenStackInstance,
                exists=lambda _: True,
                get_created=lambda _: nuke.OPENSTACK_DELAY + 1,
                __getitem__=lambda _, key: name,
                destroy=DEFAULT,
                ) as m:
            nuke.stale_openstack_instances(ctx, {
                uuid: { 'Name': name, },
            }, {
                misc.canonicalize_hostname(name, user=None): {},
            })
            m['destroy'].assert_not_called()


@patch("teuthology.lock.ops.unlock_one")
def test_nuke_internal(m_unlock_one):
    job_config = dict(
        owner='test_owner',
        targets={'user@host1': 'key1', 'user@host2': 'key2'},
        archive_path='/path/to/test_run',
        machine_type='test_machine',
        os_type='centos',
        os_version='8.3',
        name='test_name',
    )
    statuses = {
        target: {'name': target, 'description': job_config['name']}
        for target in job_config['targets'].keys()
    }
    ctx = create_fake_context(job_config)

    # minimal call using defaults
    with patch.multiple(
            nuke,
            nuke_helper=DEFAULT,
            get_status=lambda i: statuses[i],
            ) as m:
        nuke.nuke(ctx, True)
        m['nuke_helper'].assert_called_with(ANY, True, False, True)
        m_unlock_one.assert_called()
    m_unlock_one.reset_mock()

    # don't unlock
    with patch.multiple(
            nuke,
            nuke_helper=DEFAULT,
            get_status=lambda i: statuses[i],
            ) as m:
        nuke.nuke(ctx, False)
        m['nuke_helper'].assert_called_with(ANY, False, False, True)
        m_unlock_one.assert_not_called()
    m_unlock_one.reset_mock()

    # mimicing what teuthology-dispatcher --supervisor does
    with patch.multiple(
            nuke,
            nuke_helper=DEFAULT,
            get_status=lambda i: statuses[i],
            ) as m:
        nuke.nuke(ctx, False, True, False, True, False)
        m['nuke_helper'].assert_called_with(ANY, False, True, False)
        m_unlock_one.assert_not_called()
    m_unlock_one.reset_mock()

    # no targets
    del ctx.config['targets']
    with patch.multiple(
            nuke,
            nuke_helper=DEFAULT,
            get_status=lambda i: statuses[i],
            ) as m:
        nuke.nuke(ctx, True)
        m['nuke_helper'].assert_not_called()
        m_unlock_one.assert_not_called()
