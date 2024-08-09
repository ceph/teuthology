import os
import yaml

from teuthology import report
from teuthology.jobqueue.base import QueueDirection
from teuthology.misc import get_user, merge_configs
import teuthology.jobqueue.choice


def main(args):
    if not args['--first-in-suite']:
        first_job_args = ['subset', 'no-nested-subset', 'seed']
        for arg in first_job_args:
            opt = '--{arg}'.format(arg=arg)
            msg_fmt = '{opt} is only applicable to the first job in a suite'
            if args.get(opt):
                raise ValueError(msg_fmt.format(opt=opt))

    if not args['--last-in-suite']:
        last_job_args = ['email', 'timeout']
        for arg in last_job_args:
            opt = '--{arg}'.format(arg=arg)
            msg_fmt = '{opt} is only applicable to the last job in a suite'
            if args[opt]:
                raise ValueError(msg_fmt.format(opt=opt))

    if args['--first-in-suite'] or args['--last-in-suite']:
        report_status = False
    else:
        report_status = True

    name = args['--name']
    if not name or name.isdigit():
        raise ValueError("Please use a more descriptive value for --name")
    job_config = build_config(args)
    if args['--dry-run']:
        print('---\n' + yaml.safe_dump(job_config))
        return
    queue = select_queue(args['--queue-backend'], job_config)
    schedule_job(queue, job_config, args['--num'], report_status)


def build_config(args):
    """
    Given a dict of arguments, build a job config
    """
    config_paths = args.get('<conf_file>', list())
    conf_dict = merge_configs(config_paths)
    # strip out targets; the worker will allocate new ones when we run
    # the job with --lock.
    if 'targets' in conf_dict:
        del conf_dict['targets']
    args['config'] = conf_dict

    owner = args['--owner']
    if owner is None:
        owner = 'scheduled_{user}'.format(user=get_user())

    job_config = dict(
        name=args['--name'],
        first_in_suite=args['--first-in-suite'],
        last_in_suite=args['--last-in-suite'],
        email=args['--email'],
        description=args['--description'],
        owner=owner,
        verbose=args['--verbose'],
        machine_type=args['--worker'],
        tube=args['--worker'],
        priority=int(args['--priority']),
    )
    # Update the dict we just created, and not the other way around, to let
    # settings in the yaml override what's passed on the command line. This is
    # primarily to accommodate jobs with multiple machine types.
    job_config.update(conf_dict)
    for arg,conf in {'--timeout':'results_timeout',
                     '--seed': 'seed',
                     '--subset': 'subset',
                     '--no-nested-subset': 'no_nested_subset'}.items():
        val = args.get(arg, None)
        if val is not None:
            job_config[conf] = val

    return job_config


def schedule_job(queue, job_config, num=1, report_status=True):
    """
    Schedule a job.

    :param queue: Job queue object
    :param job_config: The complete job dict
    :param num:      The number of times to schedule the job
    :param report_status: Enable or disable reporting job
    """
    for _ in range(int(num)):
        queue.put(job_config)
        if report_status:
            report.try_push_job_info(job_config, dict(status='queued'))


def select_queue(backend, job_config):
    """
    Select the kind of job queue to use.

    :param backend: String name of queue
    :param job_config: The complete job dict
    """
    tube = job_config.get('tube', '')
    return teuthology.jobqueue.choice.from_backend(
        backend, tube, QueueDirection.IN
    )
