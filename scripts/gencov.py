import docopt

import teuthology.coverage_report
import teuthology.gencov
import sys

doc = """
usage:  teuthology-gencov -h
	teuthology-gencov   <run-name>

      """

def main(argv=sys.argv[1:]):
	args = docopt.docopt(doc, argv=argv)
	teuthology.gencov.main(args)

