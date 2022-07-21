import logging
from textwrap import dedent

from mock import patch, MagicMock
from unittest import TestCase

from teuthology.suite import build_matrix
from teuthology.suite.merge import config_merge
from teuthology.test.fake_fs import make_fake_fstools

log = logging.getLogger(__name__)

class TestMerge(TestCase):
    patchpoints = [
        'os.path.exists',
        'os.listdir',
        'os.path.isfile',
        'os.path.isdir',
        'builtins.open',
    ]

    def setUp(self):
        log.debug("setUp")
        self.mocks = dict()
        self.patchers = dict()
        for ppoint in self.__class__.patchpoints:
            self.mocks[ppoint] = MagicMock()
            self.patchers[ppoint] = patch(ppoint, self.mocks[ppoint])

    def start_patchers(self, fake_fs):
        fake_fns = make_fake_fstools(fake_fs)
        # N.B.: relies on fake_fns being in same order as patchpoints
        for ppoint, fn in zip(self.__class__.patchpoints, fake_fns):
            self.mocks[ppoint].side_effect = fn
            self.patchers[ppoint].start()

    def stop_patchers(self):
        for patcher in self.patchers.values():
            patcher.stop()

    def tearDown(self):
        log.debug("tearDown")
        self.patchers.clear()
        self.mocks.clear()

    def test_premerge(self):
        fake_fs = {
            'd0_0': {
                '%': None,
                'd1_0': {
                  'a.yaml': dedent("""
                  teuthology:
                    premerge: reject()
                  foo: bar
                  """),
                },
                'c.yaml': dedent("""
                top: pot
                """),
            },
        }
        self.start_patchers(fake_fs)
        try:
            result = build_matrix.build_matrix('d0_0')
            self.assertEqual(len(result), 1)
            configs = list(config_merge(result))
            self.assertEqual(len(configs), 1)
            desc, frags, yaml = configs[0]
            self.assertIn("top", yaml)
            self.assertNotIn("foo", yaml)
        finally:
            self.stop_patchers()

    def test_postmerge(self):
        fake_fs = {
            'd0_0': {
                '%': None,
                'd1_0': {
                  'a.yaml': dedent("""
                  teuthology:
                    postmerge:
                      - reject()
                  foo: bar
                  """),
                  'b.yaml': dedent("""
                  baz: zab
                  """),
                },
                'c.yaml': dedent("""
                top: pot
                """),
            },
        }
        self.start_patchers(fake_fs)
        try:
            result = build_matrix.build_matrix('d0_0')
            self.assertEqual(len(result), 2)
            configs = list(config_merge(result))
            self.assertEqual(len(configs), 1)
            desc, frags, yaml = configs[0]
            self.assertIn("top", yaml)
            self.assertIn("baz", yaml)
            self.assertNotIn("foo", yaml)
        finally:
            self.stop_patchers()

    def test_postmerge_concat(self):
        fake_fs = {
            'd0_0': {
                '%': None,
                'd1_0': {
                  'a.yaml': dedent("""
                  teuthology:
                    postmerge:
                      - local a = 1
                  foo: bar
                  """),
                  'b.yaml': dedent("""
                  teuthology:
                    postmerge:
                      - local a = 2
                  baz: zab
                  """),
                },
                'z.yaml': dedent("""
                 teuthology:
                   postmerge:
                     - if a == 1 then reject() end
                 top: pot
                 """),
            },
        }
        self.start_patchers(fake_fs)
        try:
            result = build_matrix.build_matrix('d0_0')
            self.assertEqual(len(result), 2)
            configs = list(config_merge(result))
            self.assertEqual(len(configs), 1)
            desc, frags, yaml = configs[0]
            self.assertIn("top", yaml)
            self.assertIn("baz", yaml)
            self.assertNotIn("foo", yaml)
        finally:
            self.stop_patchers()


    def test_yaml_mutation(self):
        fake_fs = {
            'd0_0': {
                '%': None,
                'c.yaml': dedent("""
                teuthology:
                  postmerge:
                    - |
                      yaml["test"] = py_dict()
                top: pot
                """),
            },
        }
        self.start_patchers(fake_fs)
        try:
            result = build_matrix.build_matrix('d0_0')
            self.assertEqual(len(result), 1)
            configs = list(config_merge(result))
            self.assertEqual(len(configs), 1)
            desc, frags, yaml = configs[0]
            self.assertIn("test", yaml)
            self.assertDictEqual(yaml["test"], {})
        finally:
            self.stop_patchers()

    def test_sandbox(self):
        fake_fs = {
            'd0_0': {
                '%': None,
                'c.yaml': dedent("""
                teuthology:
                  postmerge:
                    - |
                      log.debug("_ENV contains:")
                      for k,v in pairs(_ENV) do
                        log.debug("_ENV['%s'] = %s", tostring(k), tostring(v))
                      end
                      local check = {
                        "assert",
                        "error",
                        "ipairs",
                        "next",
                        "pairs",
                        "tonumber",
                        "tostring",
                        "py_attrgetter",
                        "py_dict",
                        "py_list",
                        "py_tuple",
                        "py_enumerate",
                        "py_iterex",
                        "py_itemgetter",
                        "math",
                        "reject",
                        "accept",
                        "deep_merge",
                        "log",
                        "reject",
                        "yaml_load",
                      }
                      for _,v in ipairs(check) do
                        log.debug("checking %s", tostring(v))
                        assert(_ENV[v])
                      end
                      local block = {
                        "coroutine",
                        "debug",
                        "io",
                        "os",
                        "package",
                      }
                      for _,v in ipairs(block) do
                        log.debug("checking %s", tostring(v))
                        assert(_ENV[v] == nil)
                      end
                top: pot
                """),
            },
        }
        self.start_patchers(fake_fs)
        try:
            result = build_matrix.build_matrix('d0_0')
            self.assertEqual(len(result), 1)
            configs = list(config_merge(result))
            self.assertEqual(len(configs), 1)
        finally:
            self.stop_patchers()
