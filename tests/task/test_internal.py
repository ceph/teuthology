from unittest.mock import patch

from teuthology.config import FakeNamespace
from teuthology.task import internal


class TestInternal(object):
    def setup_method(self):
        self.ctx = FakeNamespace()
        self.ctx.config = dict()

    def test_buildpackages_prep(self):
        #
        # no buildpackages nor install tasks
        #
        self.ctx.config = { 'tasks': [] }
        assert internal.buildpackages_prep(self.ctx,
                                           self.ctx.config) == internal.BUILDPACKAGES_NOTHING
        #
        # make the buildpackages tasks the first to run
        #
        self.ctx.config = {
            'tasks': [ { 'atask': None },
                       { 'internal.buildpackages_prep': None },
                       { 'btask': None },
                       { 'install': None },
                       { 'buildpackages': None } ],
        }
        assert internal.buildpackages_prep(self.ctx,
                                           self.ctx.config) == internal.BUILDPACKAGES_FIRST
        assert self.ctx.config == {
            'tasks': [ { 'atask': None },
                       { 'internal.buildpackages_prep': None },
                       { 'buildpackages': None },
                       { 'btask': None },
                       { 'install': None } ],
        }
        #
        # the buildpackages task already the first task to run
        #
        assert internal.buildpackages_prep(self.ctx,
                                           self.ctx.config) == internal.BUILDPACKAGES_OK
        #
        # no buildpackages task
        #
        self.ctx.config = {
            'tasks': [ { 'install': None } ],
        }
        assert internal.buildpackages_prep(self.ctx,
                                           self.ctx.config) == internal.BUILDPACKAGES_NOTHING
        #
        # no install task: the buildpackages task must be removed
        #
        self.ctx.config = {
            'tasks': [ { 'buildpackages': None } ],
        }
        assert internal.buildpackages_prep(self.ctx,
                                           self.ctx.config) == internal.BUILDPACKAGES_REMOVED
        assert self.ctx.config == {'tasks': []}

    @patch("teuthology.task.internal.packaging.get_builder_project")
    def test_check_packages_default_os(self, m_get_builder_project):
        self.ctx.os_type = None
        self.ctx.os_version = None
        self.ctx.config = {'tasks': [], 'sha1': 'abc123'}
        internal.check_packages(self.ctx, self.ctx.config)
        project, job_config = m_get_builder_project.return_value.call_args.args
        assert job_config['os_type'] == 'ubuntu'
        assert job_config['os_version'] == '24.04'
        assert 'os_type' not in self.ctx.config

    @patch("teuthology.task.internal.packaging.get_builder_project")
    def test_check_packages_job_os(self, m_get_builder_project):
        self.ctx.os_type = None
        self.ctx.os_version = None
        self.ctx.config = {'tasks': [], 'sha1': 'abc123',
                           'os_type': 'centos', 'os_version': '9.stream'}
        internal.check_packages(self.ctx, self.ctx.config)
        project, job_config = m_get_builder_project.return_value.call_args.args
        assert job_config['os_type'] == 'centos'
        assert job_config['os_version'] == '9.stream'
