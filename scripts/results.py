"""
usage: teuthology-results [-h] [-v] [--dry-run] [--email EMAIL] [--timeout TIMEOUT] --archive-dir DIR --name NAME

Email teuthology suite results

optional arguments:
  -h, --help         Show this help message and exit
  -v, --verbose      Se more verbose
  --dry-run          Instead of sending the email, just print it
  --email EMAIL      Address to email test failures to
  --timeout TIMEOUT  How many seconds to wait for all tests to finish
                     [default: 0]
  --archive-dir DIR  Path under which results for the suite are stored
  --name NAME        Name of the suite
"""
import docopt
import teuthology.results


def main():
    args = docopt.docopt(__doc__)
    teuthology.results.main(args)
