import docopt
import sys

import teuthology.polarion

doc = """
usage: teuthology-polarion --help
       teuthology-polarion --suite <suite> --suite-dir <suite-dir> [--output <argument>]
       teuthology-polarion --suite <suite> --suite-repo <suite-repo> --suite-branch <suite-branch> [--output <argument>] 
       
generate unique polarion_id/desc based on frag_id in suite yaml

Standard arguments:
  -s <suite>, --suite <suite>          The suite to generate polarion_ids
  --suite-repo <suite-repo>            Use tasks and suite definition in this repository
                                       
  --suite-branch <suite-branch>        Use this suite branch instead of the ceph branch
  --suite-dir <suite-dir>              Use this alternative directory if you have suite 
                                       directory present in local disk
  --output <output>                    write the frag_ids to a file, supported types are .csv
"""


def main(argv=sys.argv[1:]):
    args = docopt.docopt(doc, argv=argv)
    teuthology.polarion.main(args)
