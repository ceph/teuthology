"""
usage: teuthology-results [-h] [-v] [--dry-run] [--email EMAIL] [--timeout TIMEOUT] --archive-dir DIR --name NAME

Email teuthology suite results

optional arguments:
  -h, --help         show this help message and exit
  -v, --verbose      be more verbose
  --config-file      path to the config file (default ~/.teuthology.yaml)
  --dry-run          Instead of sending the email, just print it
  --email EMAIL      address to email test failures to
  --timeout TIMEOUT  how many seconds to wait for all tests to finish (default
                     no wait)
  --archive-dir DIR  path under which results for the suite are stored
  --name NAME        name of the suite
"""
import docopt
import teuthology.results


def main():
    args = docopt.docopt(__doc__)
    teuthology.results.main(args)
