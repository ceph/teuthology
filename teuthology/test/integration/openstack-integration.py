from cStringIO import StringIO
import argparse
import logging
import json
import testtools
import sys

from mock import patch

import teuthology.lock
import teuthology.misc
import scripts.lock
from teuthology.config import config


class TestLock(testtools.TestCase):

    @classmethod
    def setUpClass(self):
        teuthology.log.setLevel(logging.DEBUG)
        teuthology.misc.read_config(argparse.Namespace())
        self.tearDownClass()

    @classmethod
    def tearDownClass(self):
        self.first_machine = 10
        self.last_machine = 19
        # if this fails it will not show the error but some weird
        # INTERNALERROR> IndexError: list index out of range
        # move that to def tearDown for debug and when it works move it
        # back in tearDownClass so it is not called on every test
        self.openstack = config.openstack['clusters'].keys()[0]
        teuthology.misc.sh("""
set -ex
cd ../paddles
(
    echo "delete from nodes;"
    for id in $(seq {first} {last}) ; do
        echo "insert into nodes (id,name,machine_type,is_vm,locked,up) values ($id, '{openstack}0$id', 'openstack', 1, 0, 1);" # noqa
    done
) | sqlite3 dev.db
        """.format(openstack=self.openstack,
                   first=self.first_machine,
                   last=self.last_machine))
        self.machine = self.openstack + '0' + str(self.first_machine)

    def setUp(self):
        super(TestLock, self).setUp()
        self.options = ['--verbose']

    def tearDown(self):
        super(TestLock, self).tearDown()

    def test_main(self):
        args = scripts.lock.parse_args(self.options + ['--lock'])
        assert teuthology.lock.main(args) == 0

    @patch('teuthology.provision.OpenStack.create')
    @patch('teuthology.provision.OpenStack.destroy')
    def test_create_destroy(self, m_destroy, m_create):
        args = scripts.lock.parse_args(self.options +
                                       ['--lock', self.machine])
        assert teuthology.lock.main(args) == 0
        assert m_create.called
        args = scripts.lock.parse_args(self.options +
                                       ['--unlock', self.machine])
        assert teuthology.lock.main(args) == 0
        assert m_destroy.called

    def test_lock_unlock_default(self):
        args = scripts.lock.parse_args(self.options +
                                       ['--lock', self.machine])
        assert teuthology.lock.main(args) == 0
        args = scripts.lock.parse_args(self.options +
                                       ['--unlock', self.machine])
        assert teuthology.lock.main(args) == 0

    def test_lock_unlock_centos_7(self):
        args = scripts.lock.parse_args(self.options +
                                       ['--lock',
                                        '--os-type=centos',
                                        '--os-version=7.0',
                                        self.machine])
        assert teuthology.lock.main(args) == 0
        args = scripts.lock.parse_args(self.options +
                                       ['--unlock', self.machine])
        assert teuthology.lock.main(args) == 0

    def test_list(self):
        my_stream = StringIO()
        self.patch(sys, 'stdout', my_stream)
        args = scripts.lock.parse_args(self.options + ['--list', '--all'])
        teuthology.lock.main(args)
        out = my_stream.getvalue()
        logging.info('--list --all : ' + out)
        self.assertIn('machine_type', out)
        self.assertIn('openstack', out)
        openstack = config.openstack['clusters'].keys()[0]
        machine = openstack + '011'
        logging.info('looking for ' + machine)
        self.assertIn(machine, out)
        status = json.loads(out)
        self.assertEquals(self.last_machine - self.first_machine + 1,
                          len(status))
