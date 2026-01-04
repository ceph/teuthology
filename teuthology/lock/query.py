import datetime
import logging
import os
import requests

from typing import Dict, List, Union

from teuthology import misc
from teuthology.config import config
from teuthology.contextutil import safe_while
from teuthology.util.compat import urlencode
from teuthology.util.time import parse_timestamp


log = logging.getLogger(__name__)


def get_status(name) -> dict:
    name = misc.canonicalize_hostname(name, user=None)
    uri = os.path.join(config.lock_server, 'nodes', name, '')
    with safe_while(
            sleep=1, increment=0.5, action=f'get_status {name}') as proceed:
        while proceed():
            response = requests.get(uri)
            if response.ok:
                return response.json()
            elif response.status_code == 404:
                return dict()
    log.warning(
        "Failed to query lock server for status of {name}".format(name=name))
    return dict()


def get_statuses(machines):
    if machines:
        statuses = []
        for machine in machines:
            machine = misc.canonicalize_hostname(machine)
            status = get_status(machine)
            if status:
                statuses.append(status)
            else:
                log.error("Lockserver doesn't know about machine: %s" %
                          machine)
    else:
        statuses = list_locks()
    return statuses


def is_vm(name=None, status=None):
    if status is None:
        if name is None:
            raise ValueError("Must provide either name or status, or both")
        name = misc.canonicalize_hostname(name)
        status = get_status(name)
    return status.get('is_vm', False)


def list_locks(keyed_by_name=False, tries=10, **kwargs):
    uri = os.path.join(config.lock_server, 'nodes', '')
    for key, value in kwargs.items():
        if kwargs[key] is False:
            kwargs[key] = '0'
        if kwargs[key] is True:
            kwargs[key] = '1'
    if kwargs:
        if 'machine_type' in kwargs:
            kwargs['machine_type'] = kwargs['machine_type'].replace(',','|')
        uri += '?' + urlencode(kwargs)
    with safe_while(
            sleep=1,
            increment=0.5,
            tries=tries,
            action='list_locks'
    ) as proceed:
        while proceed():
            try:
                response = requests.get(uri)
                if response.ok:
                    break
            except requests.ConnectionError:
                log.exception("Could not contact lock server: %s, retrying...", config.lock_server)
    if response.ok:
        if not keyed_by_name:
            return response.json()
        else:
            return {node['name']: node
                    for node in response.json()}
    return dict()


def find_stale_locks(owner=None) -> List[Dict]:
    """
    Return a list of node dicts corresponding to nodes that were locked to run
    a job, but the job is no longer running. The purpose of this is to enable
    us to find nodes that were left locked due to e.g. infrastructure failures
    and return them to the pool.

    :param owner: If non-None, return nodes locked by owner. Default is None.
    """
    def might_be_stale(node_dict):
        """
        Answer the question: "might this be a stale lock?"

        The answer is yes if:
            It is locked
            It has a non-null description containing multiple '/' characters

        ... because we really want "nodes that were locked for a particular job
        and are still locked" and the above is currently the best way to guess.
        """
        desc = node_dict['description']
        if (node_dict['locked'] is True and
            desc is not None and desc.startswith('/') and
                desc.count('/') > 1):
            return True
        return False

    # Which nodes are locked for jobs?
    nodes = list_locks(locked=True)
    if owner is not None:
        nodes = [node for node in nodes if node['locked_by'] == owner]
    nodes = filter(might_be_stale, nodes)

    # Here we build the list of of nodes that are locked, for a job (as opposed
    # to being locked manually for random monkeying), where the job is not
    # running
    result = list()
    for node in nodes:
        if node_active_job(node["name"], grace_time=5):
            continue
        result.append(node)
    return result

def node_active_job(name: str, status: Union[dict, None] = None, grace_time: int = 0) -> Union[str, None]:
    """
    Is this node's job active (e.g. running or waiting)?

    :param node:  The node dict as returned from the lock server
    :param cache: A set() used for caching results
    :param grace: A period of time (in mins) after job finishes before we consider the node inactive
    :returns:     A string if the node has an active job, or None if not
    """
    status = status or get_status(name)
    if not status:
        # This should never happen with a normal node
        return "node had no status"
    description = status['description']
    if '/' not in description:
        # technically not an "active job", but someone locked the node
        # for a different purpose and is likely still using it.
        return description
    (run_name, job_id) = description.split('/')[-2:]
    if not run_name or job_id == '':
        # We thought this node might have a stale job, but no.
        return "node description does not contained scheduled job info"
    url = f"{config.results_server}/runs/{run_name}/jobs/{job_id}/"
    job_status = ""
    # suppose results' server is in the same timezone as we are here
    tzhere = datetime.datetime.now().astimezone().tzinfo
    active = True
    with safe_while(
            sleep=1, increment=0.5, action='node_is_active') as proceed:
        while proceed():
            resp = requests.get(url)
            if resp.ok:
                job_obj = resp.json()
                job_status = job_obj["status"]
                active = job_status and job_status not in ('pass', 'fail', 'dead')
                if active:
                    break
                job_updated = job_obj["updated"]
                if not grace_time:
                    break
                try:
                    now = datetime.datetime.now(datetime.timezone.utc)
                    delta = now - parse_timestamp(job_updated, tzhere)
                    active = active or delta < datetime.timedelta(minutes=grace_time)
                except Exception:
                    log.exception(f"{run_name}/{job_id} updated={job_updated}")
                break
            elif resp.status_code == 404:
                break
            else:
                log.debug(f"Error {resp.status_code} listing job {run_name}/{job_id} for {name}: {resp.text}")
    if active:
        return description
