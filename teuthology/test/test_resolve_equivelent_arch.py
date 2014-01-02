from .. import misc as teuthology

class Mock: pass

class TestResolveEquivelentArch(object):

    def test_forward_64(self):
        arch = teuthology.resolve_equivelent_arch('x86_64')
        assert 'x86_64' in arch
        assert '64-bit' in arch
        assert 'amd64' in arch

    def test_forward_32(self):
        arch = teuthology.resolve_equivelent_arch('i386')
        assert 'i386' in arch
        assert '32-bit' in arch
        assert 'i686' in arch

    def test_forward_arm(self):
        arch = teuthology.resolve_equivelent_arch('armv7l')
        assert 'armv7l' in arch
        assert 'armhf' in arch
        assert 'arm' in arch

    def test_reverse_64(self):
        for arch in ['x86_64', '64-bit', 'amd64']:
            assert teuthology.resolve_equivelent_arch(arch, reverse=True) == 'x86_64'

    def test_reverse_32(self):
        for arch in ['i386', '32-bit', 'i686']:
            assert teuthology.resolve_equivelent_arch(arch, reverse=True) == 'i386'

    def test_reverse_arm(self):
        for arch in ['armv7l', 'armhf', 'arm']:
            assert teuthology.resolve_equivelent_arch(arch, reverse=True) == 'armv7l'
