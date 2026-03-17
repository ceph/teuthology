import argparse

import teuthology.config
import teuthology.report

def main():
    parser = argparse.ArgumentParser(
        description='Submit test results to a web service',
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='be more verbose'
    )
    parser.add_argument(
        '-a', '--archive',
        default=teuthology.config.config.archive_base,
        help=f'The base archive directory (default: {teuthology.config.config.archive_base})'
    )
    parser.add_argument(
        '-r', '--run',
        nargs='*',
        help='A run (or list of runs) to submit'
    )
    parser.add_argument(
        '-j', '--job',
        nargs='*',
        help='A job (or list of jobs) to submit'
    )
    parser.add_argument(
        '--all-runs',
        action='store_true',
        help='Submit all runs in the archive'
    )
    parser.add_argument(
        '-R', '--refresh',
        action='store_true',
        help='Re-push any runs already stored on the server. Note that this may be slow.'
    )
    parser.add_argument(
        '-s', '--server',
        help="The server to post results to, e.g. http://localhost:8080/ . May also be specified in ~/.teuthology.yaml as 'results_server'"
    )
    parser.add_argument(
        '-n', '--no-save',
        action='store_true',
        help="By default, when submitting all runs, we remember the last successful submission in a file called 'last_successful_run'. Pass this flag to disable that behavior."
    )
    parser.add_argument(
        '-D', '--dead',
        action='store_true',
        help="Mark all given jobs (or entire runs) with status 'dead'. Implies --refresh."
    )
    args = parser.parse_args()
    teuthology.report.main(args.__dict__)
