import sys
import logging
from .sentry import submit_event as submit_sentry_event
from .job_status import set_status
from .exceptions import ConnectionLostError

log = logging.getLogger(__name__)


def import_task(name):
    internal_pkg = __import__('teuthology.task', globals(), locals(), [name],
                              0)
    if hasattr(internal_pkg, name):
        return getattr(internal_pkg, name)
    else:
        external_pkg = __import__('tasks', globals(), locals(),
                                  [name], 0)
    if hasattr(external_pkg, name):
        return getattr(external_pkg, name)
    raise ImportError("Could not find task '%s'" % name)


def run_one_task(taskname, **kwargs):
    submod = taskname
    subtask = 'task'
    if '.' in taskname:
        (submod, subtask) = taskname.rsplit('.', 1)

    # Teuthology configs may refer to modules like ceph_deploy as ceph-deploy
    submod = submod.replace('-', '_')

    task = import_task(submod)
    try:
        fn = getattr(task, subtask)
    except AttributeError:
        log.error("No subtask of %s named %s was found", task, subtask)
        raise
    return fn(**kwargs)


def run_tasks(tasks, ctx):
    stack = []
    try:
        for taskdict in tasks:
            try:
                ((taskname, config),) = taskdict.iteritems()
            except (ValueError, AttributeError):
                raise RuntimeError('Invalid task definition: %s' % taskdict)
            log.info('Running task %s...', taskname)
            manager = run_one_task(taskname, ctx=ctx, config=config)
            if hasattr(manager, '__enter__'):
                stack.append((taskname, manager))
                manager.__enter__()
    except BaseException as e:
        if isinstance(e, ConnectionLostError):
            # Prevent connection issues being flagged as failures
            set_status(ctx.summary, 'dead')
        else:
            # the status may have been set to dead, leave it as-is if so
            if not ctx.summary.get('status', '') == 'dead':
                set_status(ctx.summary, 'fail')
        if 'failure_reason' not in ctx.summary:
            ctx.summary['failure_reason'] = str(e)
        log.exception('Saw exception from tasks.')

        submit_sentry_event(ctx, taskname)

        if ctx.config.get('interactive-on-error'):
            ctx.config['interactive-on-error'] = False
            from .task import interactive
            log.warning('Saw failure during task execution, going into interactive mode...')
            interactive.task(ctx=ctx, config=None)
        # Throughout teuthology, (x,) = y has been used to assign values
        # from yaml files where only one entry of type y is correct.  This
        # causes failures with 'too many values to unpack.'  We want to
        # fail as before, but with easier to understand error indicators.
        if type(e) == ValueError:
            if e.message == 'too many values to unpack':
                emsg = 'Possible configuration error in yaml file'
                log.error(emsg)
                ctx.summary['failure_info'] = emsg
    finally:
        try:
            exc_info = sys.exc_info()
            while stack:
                taskname, manager = stack.pop()
                log.debug('Unwinding manager %s', taskname)
                try:
                    suppress = manager.__exit__(*exc_info)
                except Exception as e:
                    if isinstance(e, ConnectionLostError):
                        # Prevent connection issues being flagged as failures
                        set_status(ctx.summary, 'dead')
                    else:
                        set_status(ctx.summary, 'fail')
                    if 'failure_reason' not in ctx.summary:
                        ctx.summary['failure_reason'] = str(e)
                    log.exception('Manager failed: %s', taskname)

                    if exc_info == (None, None, None):
                        # if first failure is in an __exit__, we don't
                        # have exc_info set yet
                        exc_info = sys.exc_info()

                    if ctx.config.get('interactive-on-error'):
                        from .task import interactive
                        log.warning(
                            'Saw failure during task cleanup, going into interactive mode...')
                        interactive.task(ctx=ctx, config=None)
                else:
                    if suppress:
                        sys.exc_clear()
                        exc_info = (None, None, None)

            if exc_info != (None, None, None):
                log.debug('Exception was not quenched, exiting: %s: %s',
                          exc_info[0].__name__, exc_info[1])
                raise SystemExit(1)
        finally:
            # be careful about cyclic references
            del exc_info
