import argparse

import teuthology.config
import teuthology.describe_tests

desc = """
Describe the contents of a qa suite by reading 'meta' elements from
yaml files in the suite.

The 'meta' element should contain a list with a dictionary
of key/value pairs for entries, i.e.:

meta:
- field1: value1
  field2: value2
  field3: value3
  desc: short human-friendly description

Fields are user-defined, and are not required to be in all yaml files.
"""

def main():
    parser = argparse.ArgumentParser(
        description=desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'suite_dir',
        metavar='<suite_dir>',
        help='path of qa suite'
    )
    parser.add_argument(
        '-f', '--fields',
        default='desc',
        metavar='<fields>',
        help='Comma-separated list of fields to include (default: desc)'
    )
    parser.add_argument(
        '--show-facet',
        default='yes',
        choices=['yes', 'no'],
        help='List the facet of each file (default: yes)'
    )
    parser.add_argument(
        '--format',
        default='plain',
        choices=['plain', 'json', 'csv'],
        help='Output format (written to stdout) (default: plain)'
    )
    parser.add_argument(
        '-c', '--combinations',
        action='store_true',
        help='Describe test combinations rather than individual yaml fragments'
    )
    parser.add_argument(
        '-s', '--summary',
        action='store_true',
        help='Print summary'
    )
    parser.add_argument(
        '--filter', '--filter-in',
        metavar='<keywords>',
        help='Only list tests whose description contains at least one of the keywords in the comma separated keyword string specified'
    )
    parser.add_argument(
        '--filter-out',
        metavar='<keywords>',
        help='Do not list tests whose description contains any of the keywords in the comma separated keyword string specified'
    )
    parser.add_argument(
        '--filter-all',
        metavar='<keywords>',
        help='Only list tests whose description contains each of the keywords in the comma separated keyword string specified'
    )
    parser.add_argument(
        '-F', '--filter-fragments',
        action='store_true',
        help="Check fragments additionaly to descriptions using keywords specified with 'filter', 'filter-out' and 'filter-all' options"
    )
    parser.add_argument(
        '-p', '--print-description',
        action='store_true',
        help="Print job descriptions for the suite, used only in combination with 'summary'"
    )
    parser.add_argument(
        '-P', '--print-fragments',
        action='store_true',
        help="Print file list inovolved for each facet, used only in combination with 'summary'"
    )
    parser.add_argument(
        '-l', '--limit',
        type=int,
        default=0,
        metavar='<jobs>',
        help='List at most this many jobs (default: 0)'
    )
    parser.add_argument(
        '--subset',
        metavar='<index/outof>',
        help='Instead of listing the entire suite, break the set of jobs into <outof> pieces (each of which will contain each facet at least once) and list piece <index>. Listing 0/<outof>, 1/<outof>, 2/<outof> ... <outof>-1/<outof> will list all jobs in the suite (many more than once).'
    )
    parser.add_argument(
        '-S', '--seed',
        type=int,
        default=-1,
        metavar='<seed>',
        help='Used for pseudo-random tests generation involving facet whose path ends with $ operator, where negative value used for a random seed (default: -1)'
    )
    parser.add_argument(
        '--no-nested-subset',
        action='store_true',
        help='Disable nested subsets'
    )
    args = parser.parse_args()
    if args.filter is not None:
        args.filter_in = args.filter
    teuthology.describe_tests.main(args.__dict__)
