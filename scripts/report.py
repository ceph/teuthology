import docopt

import teuthology.report

doc = """
usage:
    teuthology-report -h
    teuthology-report [-v] [-R] [-n] [-s SERVER] [-a ARCHIVE] [-D] -r RUN ...
    teuthology-report [-v] [-s SERVER] [-a ARCHIVE] [-D] -r RUN -j JOB ...
    teuthology-report [-v] [-R] [-n] [-s SERVER] [-a ARCHIVE] --all-runs

Submit test results to a web service

optional arguments:
  -h, --help            show this help message and exit
  --config-file         path to the config file (default ~/.teuthology.yaml)
  -a ARCHIVE, --archive ARCHIVE
                        The base archive directory
                        [default: {archive_base}]
  -r [RUN ...], --run [RUN ...]
                        A run (or list of runs) to submit
  -j [JOB ...], --job [JOB ...]
                        A job (or list of jobs) to submit
  --all-runs            Submit all runs in the archive
  -R, --refresh         Re-push any runs already stored on the server. Note
                        that this may be slow.
  -s SERVER, --server SERVER
                        "The server to post results to, e.g.
                        http://localhost:8080/ . May also be specified in
                        ~/.teuthology.yaml as 'results_server'
  -n, --no-save         By default, when submitting all runs, we remember the
                        last successful submission in a file called
                        'last_successful_run'. Pass this flag to disable that
                        behavior.
  -D, --dead            Mark all given jobs (or entire runs) with status
                        'dead'. Implies --refresh.
  -v, --verbose         be more verbose
""".format(archive_base=teuthology.config.config.archive_base)


def main():
    args = docopt.docopt(doc)
    teuthology.report.main(args)
