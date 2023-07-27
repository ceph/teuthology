import logging
import sentry_sdk

from copy import deepcopy

from teuthology.config import config as teuth_config
from teuthology.misc import get_http_log_path

log = logging.getLogger(__name__)


def report_error(job_config, exception, task_name=None):
    if not teuth_config.sentry_dsn:
        return None
    sentry_sdk.init(teuth_config.sentry_dsn)
    job_config = deepcopy(job_config)

    tags = {
        'task': task_name,
        'owner': job_config.get("owner"),
    }
    optional_tags = ('teuthology_branch', 'branch', 'suite',
                     'machine_type', 'os_type', 'os_version')
    for tag in optional_tags:
        if tag in job_config:
            tags[tag] = job_config[tag]

    # Remove ssh keys from reported config
    if 'targets' in job_config:
        targets = job_config['targets']
        for host in targets.keys():
            targets[host] = '<redacted>'

    job_id = job_config.get('job_id')
    archive_path = job_config.get('archive_path')
    extras = dict(config=job_config)
    if job_id:
        extras['logs'] = get_http_log_path(archive_path, job_id)

    fingerprint = exception.fingerprint() if hasattr(exception, 'fingerprint') else None
    exc_id = sentry_sdk.capture_exception(
        error=exception,
        tags=tags,
        extras=extras,
        fingerprint=fingerprint,
    )
    event_url = "{server}/?query={id}".format(
        server=teuth_config.sentry_server.strip('/'), id=exc_id)
    log.exception(" Sentry event: %s" % event_url)
    return event_url


