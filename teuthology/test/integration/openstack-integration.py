from cStringIO import StringIO
import argparse
import logging
import json
import os
import tempfile
import testtools
import shutil
import subprocess
import sys

import teuthology.lock
import teuthology.nuke
import teuthology.misc
import teuthology.schedule
import teuthology.suite
import scripts.schedule
import scripts.lock
import scripts.suite
from teuthology import provision
from teuthology.config import config


class Integration(testtools.TestCase):

    @classmethod
    def setUpClass(self):
        teuthology.log.setLevel(logging.DEBUG)
        teuthology.misc.read_config(argparse.Namespace())
        self.tearDownClass()

    @classmethod
    def tearDownClass(self):
        os.system("sudo /etc/init.d/beanstalkd restart")
        # if this fails it will not show the error but some weird
        # INTERNALERROR> IndexError: list index out of range
        # move that to def tearDown for debug and when it works move it
        # back in tearDownClass so it is not called on every test
        self.openstack = None
        openstack = None
        for cluster_name, cluster in config.openstack['clusters'].iteritems():
            logging.info("trying OpenStack cluster " + cluster_name)
            try:
                openstack = provision.OpenStack(cluster=cluster_name)
                if openstack.images_verify():
                    self.openstack = cluster_name
                    logging.info("using OpenStack cluster " + cluster_name)
                    break
                else:
                    logging.info("skip because some images are missing")
            except subprocess.CalledProcessError:
                pass
        assert self.openstack
        all_instances = openstack.run("openstack server list -f json --long")
        for instance in json.loads(all_instances):
            if 'teuthology=' in instance['Properties']:
                openstack.run("openstack server delete --wait " + instance['ID'])
        teuthology.misc.sh("""
teuthology/test/integration/setup-openstack.sh \
  --openstack {openstack} \
  --subnet {subnet} \
  --populate-paddles
        """.format(openstack=self.openstack,
                   subnet=cluster['subnet']))
        self.images = cluster['images']

    def setup_worker(self):
        self.logs = self.d + "/log"
        os.mkdir(self.logs, 0o755)
        self.archive = self.d + "/archive"
        os.mkdir(self.archive, 0o755)
        self.worker_cmd = ("teuthology-worker --tube openstack " +
                           "-l " + self.logs + " "
                           "--archive-dir " + self.archive + " ")
        self.worker = subprocess.Popen(self.worker_cmd,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       shell=True)

    def wait_worker(self):
        if not self.worker:
            return

        (stdoutdata, stderrdata) = self.worker.communicate()
        stdoutdata = stdoutdata.decode('utf-8')
        stderrdata = stderrdata.decode('utf-8')
        logging.info(self.worker_cmd + ":" +
                     " stdout " + stdoutdata +
                     " stderr " + stderrdata + " end ")
        assert self.worker.returncode == 0
        self.worker = None

class TestSuite(Integration):

    def setUp(self):
        super(TestSuite, self).setUp()
        self.d = tempfile.mkdtemp()
        self.setup_worker()
        logging.info("TestSuite: done worker")

    def tearDown(self):
        self.wait_worker()
        shutil.rmtree(self.d)
        super(TestSuite, self).tearDown()

    def test_suite_noop(self):
        cwd = os.getcwd()
        args = ['--suite', 'noop',
                '--suite-dir', cwd + '/teuthology/test/integration',
                '--machine-type', 'openstack',
                '--verbose']
        logging.info("TestSuite:test_suite_noop")
        scripts.suite.main(args)
        self.wait_worker()
        out = subprocess.check_output("cat " + self.logs + "/worker.*", shell=True)
        self.assertIn("teuthology.worker:Success!", out)
        self.assertIn("Well done", out)

    def test_suite_nuke(self):
        cwd = os.getcwd()
        args = ['--suite', 'nuke',
                '--suite-dir', cwd + '/teuthology/test/integration',
                '--machine-type', 'openstack',
                '--verbose']
        logging.info("TestSuite:test_suite_nuke")
        scripts.suite.main(args)
        self.wait_worker()
        out = subprocess.check_output("cat " + self.logs + "/worker.*", shell=True)
        self.assertIn("teuthology.worker:Child exited with code 1", out)
        locks = teuthology.lock.list_locks(locked=True)
        assert len(locks) == 0

class TestSchedule(Integration):

    def setUp(self):
        super(TestSchedule, self).setUp()
        self.d = tempfile.mkdtemp()
        self.setup_worker()

    def tearDown(self):
        self.wait_worker()
        shutil.rmtree(self.d)
        super(TestSchedule, self).tearDown()

    def test_schedule_stop_worker(self):
        job = 'teuthology/test/integration/stop_worker.yaml'
        args = ['--name', 'fake',
                '--verbose',
                '--owner', 'test@test.com',
                '--worker', 'openstack',
                job]
        scripts.schedule.main(args)
        self.wait_worker()

    def test_schedule_noop(self):
        job = 'teuthology/test/integration/noop.yaml'
        args = ['--name', 'fake',
                '--verbose',
                '--owner', 'test@test.com',
                '--worker', 'openstack',
                job]
        scripts.schedule.main(args)
        self.wait_worker()
        out = subprocess.check_output("cat " + self.logs + "/worker.*", shell=True)
        self.assertIn("teuthology.worker:Success!", out)
        self.assertIn("Well done", out)

class TestLock(Integration):

    def setUp(self):
        super(TestLock, self).setUp()
        self.options = ['--verbose',
                        '--machine-type', 'openstack',
                        '--openstack', self.openstack]

    def tearDown(self):
        super(TestLock, self).tearDown()

    def test_main(self):
        args = scripts.lock.parse_args(self.options + ['--lock'])
        assert teuthology.lock.main(args) == 0

    def test_lock_unlock(self):
        for image in self.images.keys():
            (os_type, os_version) = image.split('-')
            args = scripts.lock.parse_args(self.options +
                                           ['--lock-many', '1',
                                            '--os-type', os_type,
                                            '--os-version', os_version])
            assert teuthology.lock.main(args) == 0
            locks = teuthology.lock.list_locks(locked=True)
            assert len(locks) == 1
            args = scripts.lock.parse_args(self.options +
                                           ['--unlock', locks[0]['name']])
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

class TestNuke(Integration):

    def setUp(self):
        super(TestNuke, self).setUp()
        self.options = ['--verbose',
                        '--machine-type', 'openstack',
                        '--openstack', self.openstack]

    def tearDown(self):
        super(TestNuke, self).tearDown()

    def test_nuke(self):
        for image in self.images.keys():
            (os_type, os_version) = image.split('-')
            args = scripts.lock.parse_args(self.options +
                                           ['--lock-many', '1',
                                            '--os-type', os_type,
                                            '--os-version', os_version])
            assert teuthology.lock.main(args) == 0
            locks = teuthology.lock.list_locks(locked=True)
            logging.info('list_locks = ' + str(locks))
            assert len(locks) == 1
            ctx = argparse.Namespace(name=None,
                                     config={
                                         'targets': { locks[0]['name']: None },
                                     },
                                     owner=locks[0]['locked_by'],
                                     teuthology_config={})
            teuthology.nuke.nuke(ctx, should_unlock=True)
            locks = teuthology.lock.list_locks(locked=True)
            assert len(locks) == 0
