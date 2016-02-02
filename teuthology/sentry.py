import logging

from copy import deepcopy
from raven import Client

from .config import config
from .misc import get_http_log_path

log = logging.getLogger(__name__)

client = None


def get_client():
    global client
    if client:
        return client

    dsn = config.sentry_dsn
    if dsn:
        client = Client(dsn=dsn)
        return client


def submit_event(ctx, task_name):
        sentry = get_client()
        if not sentry:
            return

        config = deepcopy(ctx.config)

        tags = {
            'task': task_name,
            'owner': ctx.owner,
        }
        if 'teuthology_branch' in config:
            tags['teuthology_branch'] = config['teuthology_branch']
        if 'branch' in config:
            tags['branch'] = config['branch']

        # Remove ssh keys from reported config
        if 'targets' in config:
            targets = config['targets']
            for host in targets.keys():
                targets[host] = '<redacted>'

        job_id = ctx.config.get('job_id')
        archive_path = ctx.config.get('archive_path')
        extra = dict(config=config)
        if job_id:
            extra['logs'] = get_http_log_path(archive_path, job_id)

        exc_id = sentry.get_ident(sentry.captureException(
            tags=tags,
            extra=extra,
        ))
        event_url = "{server}/?q={id}".format(
            server=config.sentry_server.strip('/'), id=exc_id)
        log.exception(" Sentry event: %s" % event_url)
        ctx.summary['sentry_event'] = event_url
