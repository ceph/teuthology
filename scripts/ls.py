"""
usage: teuthology-ls [-h] [-v] <archive_dir>

List teuthology job results

positional arguments:
  <archive_dir>            Path under which to archive results

optional arguments:
  -h, --help     Show this help message and exit
  -v, --verbose  Show reasons tests failed
"""
import docopt
import teuthology.ls


def main():
    args = docopt.docopt(__doc__)
    teuthology.ls.main(args)
