import pytest
import os
import tempfile

import teuthology
import teuthology.misc
from teuthology.openstack import TeuthologyOpenStack
import scripts.openstack

class TestTeuthologyOpenStack(object):

    def setup(self):
        if 'OS_AUTH_URL' not in os.environ:
            pytest.skip('no OS_AUTH_URL environment varialbe')
        if 'cloud.ovh.net' in os.environ['OS_AUTH_URL']:
            self.provider = 'ovh'
        elif 'control.os1.phx2' in os.environ['OS_AUTH_URL']:
            self.provider = 'redhat'
        else:
            pytest.skip('unknown OS_AUTH_URL=' +
                        os.environ['OS_AUTH_URL'])
        self.key_filename = tempfile.mktemp()
        self.key_name = 'teuthology-test'
        self.name = 'teuthology-test'
        self.clobber()
        teuthology.misc.sh("""
openstack keypair create {key_name} > {key_filename}
chmod 600 {key_filename}
        """.format(key_filename=self.key_filename,
                   key_name=self.key_name))
        self.options = ['--key-name', self.key_name,
                        '--key-filename', self.key_filename,
                        '--name', self.name,
                        '--verbose']

    def teardown(self):
        self.clobber()
        os.unlink(self.key_filename)

    def clobber(self):
        teuthology.misc.sh("""
openstack server delete {name} --wait || true
openstack keypair delete {key_name} || true
        """.format(key_name=self.key_name,
                   name=self.name))

    def test_create(self, capsys):
        teuthology_argv = [
            '--suite', 'upgrade/hammer',
            '--dry-run',
            '--ceph', 'master',
            '--kernel', 'distro',
            '--flavor', 'gcov',
            '--distro', 'ubuntu',
            '--suite-branch', 'hammer',
            '--email', 'loic@dachary.org',
            '--num', '10',
            '--limit', '23',
            '--subset', '1/2',
            '--priority', '101',
            '--timeout', '234',
            '--filter', 'trasher',
            '--filter-out', 'erasure-code',
        ]
        argv = self.options + [
            '--provider', self.provider,
        ] + teuthology_argv
        args = scripts.openstack.parse_args(argv)
        teuthology = TeuthologyOpenStack(args, None, argv)
        teuthology.user_data = 'teuthology/test/integration/user-data-test1.txt'
        teuthology.teuthology_suite = 'echo --'

        teuthology.main()
        assert 'Ubuntu 14.04' in teuthology.ssh("lsb_release -a")
        variables = teuthology.ssh("grep 'substituded variables' /var/log/cloud-init.log")
        assert "nworkers=" + str(args.simultaneous_jobs) in variables
        assert "provider=" + args.provider in variables
        assert os.environ['OS_AUTH_URL'] in variables
        run_tests = teuthology.args.integration_tests and 'yes' or 'no'
        assert "run_tests=" + run_tests in variables

        out, err = capsys.readouterr()
        assert " ".join(teuthology_argv) in out

        teuthology.teardown()
