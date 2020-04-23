import logging

import teuthology
from teuthology.config import YamlConfig
from teuthology.polarion.frag_id import BuildPolarionFragmentIds
from teuthology.polarion.write import Writer

log = logging.getLogger(__name__)


def process_args(args):
    conf = YamlConfig()
    for (key, value) in args.items():
        key = key.lstrip('--').replace('-', '_')
        conf[key] = value or ''
    return conf


def main(args):
    conf = process_args(args)
    frag_ids = BuildPolarionFragmentIds(conf)
    frag_ids.build()

    log.info('polarion_frag_ids for {}'.format(conf.suite.replace('/', ':')))
    for id, frags in frag_ids.ids:
        log.info('polarion_frag_id: {}'.format(id))
    log.info('polaion_frag_ids count is: {}'.format(len(frag_ids.ids)))

    if conf.output:
        frag_ids.write_to_file()




