import argparse
import sys

import teuthology.openstack

def main(argv=sys.argv[1:]):
    sys.exit(teuthology.openstack.main(parse_args(argv), argv))

def get_key_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--key-name',
        help='OpenStack keypair name',
    )
    parser.add_argument(
        '--key-filename',
        help='path to the ssh private key',
    )
    return parser

def get_suite_parser():
    parser = argparse.ArgumentParser()
    # copy/pasted from scripts/suite.py
    parser.add_argument(
        'config_yaml',
        nargs='*',
        help='Optional extra job yaml to include',
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true', default=None,
        help='be more verbose',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true', default=None,
        help='Do a dry run; do not schedule anything',
    )
    parser.add_argument(
        '-s', '--suite',
        help='The suite to schedule',
    )
    parser.add_argument(
        '-c', '--ceph',
        help='The ceph branch to run against',
    )
    parser.add_argument(
        '-k', '--kernel',
        help=('The kernel branch to run against; if not '
              'supplied, the installed kernel is unchanged'),
    )
    parser.add_argument(
        '-f', '--flavor',
        help=("The kernel flavor to run against: ('basic',"
              "'gcov', 'notcmalloc')"),
        default='basic',
    )
    parser.add_argument(
        '-d', '--distro',
        help='Distribution to run against',
    )
    parser.add_argument(
        '--suite-branch',
        help='Use this suite branch instead of the ceph branch',
    )
    parser.add_argument(
        '-e', '--email',
        help='When tests finish or time out, send an email here',
    )
    parser.add_argument(
        '-N', '--num',
        help='Number of times to run/queue the job',
        type=int,
        default=1,
    )
    parser.add_argument(
        '-l', '--limit',
        metavar='JOBS',
        help='Queue at most this many jobs',
        type=int,
    )
    parser.add_argument(
        '--subset',
        help=('Instead of scheduling the entire suite, break the '
              'set of jobs into <outof> pieces (each of which will '
              'contain each facet at least once) and schedule '
              'piece <index>.  Scheduling 0/<outof>, 1/<outof>, '
              '2/<outof> ... <outof>-1/<outof> will schedule all '
              'jobs in the suite (many more than once).')
    )
    parser.add_argument(
        '-p', '--priority',
        help='Job priority (lower is sooner)',
        type=int,
        default=1000,
    )
    parser.add_argument(
        '--timeout',
        help=('How long, in seconds, to wait for jobs to finish '
              'before sending email. This does not kill jobs.'),
        type=int,
        default=43200,
    )
    parser.add_argument(
        '--filter',
        help=('Only run jobs whose description contains at least one '
              'of the keywords in the comma separated keyword '
              'string specified. ')
    )
    parser.add_argument(
        '--filter-out',
        help=('Do not run jobs whose description contains any of '
              'the keywords in the comma separated keyword '
              'string specified. ')
    )
    parser.add_argument(
        '--throttle',
        help=('When scheduling, wait SLEEP seconds between jobs. '
              'Useful to avoid bursts that may be too hard on '
              'the underlying infrastructure or exceed OpenStack API '
              'limits (server creation per minute for instance).'),
        type=int,
        default=15,
    )
    parser.add_argument(
        '--suite-relpath',
        help=('Look for tasks and suite definitions in this'
              'subdirectory of the suite repo.'),
    )
    parser.add_argument(
        '-r', '--rerun',
        help=('Attempt to reschedule a run, selecting only those'
              'jobs whose status are mentioned by'
              '--rerun-status.'
              'Note that this is implemented by scheduling an'
              'entirely new suite and including only jobs whose'
              'descriptions match the selected ones. It does so'
              'using the same logic as --filter.'
              'Of all the flags that were passed when scheduling'
              'the original run, the resulting one will only'
              'inherit the suite value. Any others must be'
              'passed as normal while scheduling with this'
              'feature.'),
    )
    parser.add_argument(
        '-R', '--rerun-statuses',
        help=("A comma-separated list of statuses to be used"
              "with --rerun. Supported statuses are: 'dead',"
              "'fail', 'pass', 'queued', 'running', 'waiting'"),
        default='fail,dead',
    )
    parser.add_argument(
        '-D', '--distroversion', '--distro-version',
        help='Distro version to run against',
    )
    parser.add_argument(
        '-n', '--newest',
        help=('Search for the newest revision built on all'
              'required distro/versions, starting from'
              'either --ceph or --sha1, backtracking'
              'up to <newest> commits'),
        type=int,
        default=0,
    )
    parser.add_argument(
        '-S', '--sha1',
        help=('The ceph sha1 to run against (overrides -c)'
              'If both -S and -c are supplied, -S wins, and'
              'there is no validation that sha1 is contained'
              'in branch')
    )
    parser.add_argument(
        '--ceph-repo',
        help=("Query this repository for Ceph branch and SHA1"),
    )
    parser.add_argument(
        '--suite-repo',
        help=("Use tasks and suite definition in this repository"),
    )
    return parser

def get_openstack_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--wait',
        action='store_true', default=None,
        help='block until the suite is finished',
    )
    parser.add_argument(
        '--name',
        help='OpenStack primary instance name',
        default='teuthology',
    )
    parser.add_argument(
        '--simultaneous-jobs',
        help='maximum number of jobs running in parallel',
        type=int,
        default=1,
    )
    parser.add_argument(
        '--teardown',
        action='store_true', default=None,
        help='destroy the cluster, if it exists',
    )
    parser.add_argument(
        '--teuthology-git-url',
        help="git clone url for teuthology",
    )
    parser.add_argument(
        '--teuthology-branch',
        help="use this teuthology branch instead of master",
        default='master',
    )
    parser.add_argument(
        '--ceph-workbench-git-url',
        help="git clone url for ceph-workbench",
    )
    parser.add_argument(
        '--ceph-workbench-branch',
        help="use this ceph-workbench branch instead of master",
        default='master',
    )
    parser.add_argument(
        '--upload',
        action='store_true', default=False,
        help='upload archives to an rsync server',
    )
    parser.add_argument(
        '--archive-upload',
        help='rsync destination to upload archives',
        default='ubuntu@teuthology-logs.public.ceph.com:./',
    )
    parser.add_argument(
        '--archive-upload-url',
        help='Public facing URL where archives are uploaded',
        default='http://teuthology-logs.public.ceph.com',
    )
    parser.add_argument(
        '--no-canonical-tags',
        action='store_true', default=False,
        help='configure remote teuthology to not fetch tags from http://github.com/ceph/ceph.git in buildpackages task',
    )
    return parser

def get_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[
            get_suite_parser(),
            get_key_parser(),
            get_openstack_parser(),
        ],
        conflict_handler='resolve',
        add_help=False,
        description="""
Run a suite of ceph integration tests. A suite is a directory containing
facets. A facet is a directory containing config snippets. Running a suite
means running teuthology for every configuration combination generated by
taking one config snippet from each facet. Any config files passed on the
command line will be used for every combination, and will override anything in
the suite. By specifying a subdirectory in the suite argument, it is possible
to limit the run to a specific facet. For instance -s upgrade/dumpling-x only
runs the dumpling-x facet of the upgrade suite.

Display the http and ssh access to follow the progress of the suite
and analyze results.

  firefox http://183.84.234.3:8081/
  ssh -i teuthology-admin.pem ubuntu@183.84.234.3

""")
    return parser

def parse_args(argv):
    return get_parser().parse_args(argv)
