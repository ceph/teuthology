import os
import logging
import yaml

from teuthology.config import config
from teuthology.polarion.write import Writer
from teuthology.suite.build_matrix import build_matrix
from teuthology.polarion.util import clone_qa_suite

log = logging.getLogger(__name__)


class BuildPolarionFragmentIds:
    """
    Generate full polarion_frag_id from fragments.
    if 'frag_id' is present in fragments, then make id with it.
    """

    def __init__(self, conf):
        self._args = conf
        self.ids = set()

    @property
    def suite_path(self):
        if self._args.suite_dir:
            suite_repo_path = self._args.suite_dir
        else:
            suite_repo_path = clone_qa_suite(self._args)
        suite_rel_path = 'qa'

        return os.path.normpath(os.path.join(
            suite_repo_path,
            suite_rel_path,
            'suites',
            self._args.suite,
        ))

    @property
    def fragments(self):
        return build_matrix(self.suite_path)

    def build(self):
        for _, fragment_paths in self.fragments:
            parts = []
            frags = []  # storing frag to add as automated_script in polarion
            for fragment in fragment_paths:
                with open(fragment, 'r') as fp:
                    yml = yaml.safe_load(fp) or {}
                    if 'frag_id' in yml:
                        parts.append(yml.get('frag_id'))
                        frags.append(fp.name)
            parts = sorted([i for i in parts if i])
            id = '-'.join(parts)
            frags = ','.join(frags)
            self.ids.add((id, frags))

    def write_to_file(self):
        config.frag_ids_path = self._args.output
        config.frag_ids = self.ids
        writer = Writer()
        writer.write()
