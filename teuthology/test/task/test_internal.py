from teuthology.config import FakeNamespace
from teuthology.task import internal


class TestInternal(object):
    def setup(self):
        self.ctx = FakeNamespace()
        self.ctx.config = dict()

    def test_buildpackages(self):
        # 
        # no buildpackages nor install tasks
        #
        self.ctx.config = { 'tasks': [] }
        assert internal.buildpackages(self.ctx,
                                      self.ctx.config) == internal.BUILDPACKAGES_NOTHING
        #
        # move the buildpackages tasks before the install task
        #
        self.ctx.config = {
            'tasks': [ { 'atask': None },
                       { 'install': None },
                       { 'buildpackages': None } ],
        }
        assert internal.buildpackages(self.ctx,
                                      self.ctx.config) == internal.BUILDPACKAGES_SWAPPED
        assert self.ctx.config == {
            'tasks': [ { 'atask': None },
                       { 'buildpackages': None },
                       { 'install': None } ],
        }
        #
        # the buildpackages task already is before the install task
        #
        assert internal.buildpackages(self.ctx,
                                      self.ctx.config) == internal.BUILDPACKAGES_OK
        #
        # no buildpackages task
        #
        self.ctx.config = {
            'tasks': [ { 'install': None } ],
        }
        assert internal.buildpackages(self.ctx,
                                      self.ctx.config) == internal.BUILDPACKAGES_NOTHING
