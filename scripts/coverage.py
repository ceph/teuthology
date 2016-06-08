"""
usage: teuthology-coverage [options] -o LCOV_OUTPUT <test_dir>

Analyze the coverage of a suite of test runs, generating html output with
lcov.

options:
  -h, --help            Show this help message and exit
  -o LCOV_OUTPUT, --lcov-output LCOV_OUTPUT
                        The directory in which to store results
  --html-output HTML_OUTPUT
                        The directory in which to store html output
  --cov-tools-dir COV_TOOLS_DIR
                        The location of coverage scripts (cov-init and cov-
                        analyze) [default: ../../coverage]
  --skip-init           Skip initialization (useful if a run stopped partway
                        through)
  -v, --verbose         Be more verbose
"""
import docopt

import teuthology.coverage


def main():
    args = docopt.docopt(__doc__)
    teuthology.coverage.main(args)
