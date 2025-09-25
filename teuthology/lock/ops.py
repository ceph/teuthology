import logging
import json
import os
import random
import time
import yaml
import requests

from typing import List, Union

import teuthology.orchestra.remote
import teuthology.parallel
import teuthology.provision

from teuthology import misc, report, provision
from teuthology.config import config
from teuthology.contextutil import safe_while
from teuthology.task import console_log
from teuthology.misc import canonicalize_hostname
from teuthology.job_status import set_status

from teuthology.lock import util, query
from teuthology.orchestra import remote

log = logging.getLogger(__name__)


def update_nodes(nodes, reset_os=False):
    for node in nodes:
        remote = teuthology.orchestra.remote.Remote(
            canonicalize_hostname(node))
        if reset_os:
            log.info("Updating [%s]: reset os type and version on server", node)
            inventory_info = dict()
            inventory_info['os_type'] = ''
            inventory_info['os_version'] = ''
            inventory_info['name'] = remote.hostname
        else:
            log.info("Updating [%s]: set os type and version on server", node)
            inventory_info = remote.inventory_info
        update_inventory(inventory_info)


def lock_many_openstack(ctx, num, machine_type, user=None, description=None,
                        arch=None):
    os_type = teuthology.provision.get_distro(ctx)
    os_version = teuthology.provision.get_distro_version(ctx)
    if hasattr(ctx, 'config'):
        resources_hint = ctx.config.get('openstack')
    else:
        resources_hint = None
    machines =  teuthology.provision.openstack.ProvisionOpenStack().create(
        num, os_type, os_version, arch, resources_hint)
    result = {}
    for machine in machines:
        lock_one(machine, user, description)
        result[machine] = None # we do not collect ssh host keys yet
    return result


def lock_many(ctx, num, machine_type, user=None, description=None,
              os_type=None, os_version=None, arch=None, reimage=True):
    if user is None:
        user = misc.get_user()

    if not util.vps_version_or_type_valid(
            ctx.machine_type,
            os_type,
            os_version
    ):
        log.error('Invalid os-type or version detected -- lock failed')
        return

    # In the for loop below we can safely query for all bare-metal machine_type
    # values at once. So, if we're being asked for 'plana,mira,burnupi', do it
    # all in one shot. If we are passed 'plana,mira,burnupi,vps', do one query
    # for 'plana,mira,burnupi' and one for 'vps'
    machine_types_list = misc.get_multi_machine_types(machine_type)
    downburst_types = teuthology.provision.downburst.get_types()
    if all(t in downburst_types for t in machine_types_list):
        machine_types = machine_types_list
    elif machine_types_list == ['openstack']:
        return lock_many_openstack(ctx, num, machine_type,
                                   user=user,
                                   description=description,
                                   arch=arch)
    elif any(t in downburst_types for t in machine_types_list):
        the_vps = list(t for t in machine_types_list
                                        if t in downburst_types)
        non_vps = list(t for t in machine_types_list
                                        if not t in downburst_types)
        machine_types = ['|'.join(non_vps), '|'.join(the_vps)]
    else:
        machine_types_str = '|'.join(machine_types_list)
        machine_types = [machine_types_str, ]

    for machine_type in machine_types:
        uri = os.path.join(config.lock_server, 'nodes', 'lock_many', '')
        data = dict(
            locked_by=user,
            count=num,
            machine_type=machine_type,
            description=description,
        )
        # Only query for os_type/os_version if non-vps and non-libcloud, since
        # in that case we just create them.
        vm_types = downburst_types + teuthology.provision.cloud.get_types()
        reimage_types = teuthology.provision.get_reimage_types()
        if machine_type not in (vm_types + reimage_types):
            if os_type:
                data['os_type'] = os_type
            if os_version:
                data['os_version'] = os_version
        if arch:
            data['arch'] = arch
        log.debug("lock_many request: %s", repr(data))
        response = requests.post(
            uri,
            data=json.dumps(data),
            headers={'content-type': 'application/json'},
        )
        if response.ok:
            machines = dict()
            for machine in response.json():
                key = misc.canonicalize_hostname(
                    machine['name'],
                    user=machine.get('user'),
                )
                machines[key] = machine['ssh_pub_key']
            log.debug('locked {machines}'.format(
                machines=', '.join(machines.keys())))
            if machine_type in vm_types:
                ok_machs = {}
                update_nodes(machines, True)
                for machine in machines:
                    if teuthology.provision.create_if_vm(ctx, machine):
                        ok_machs[machine] = machines[machine]
                    else:
                        log.error('Unable to create virtual machine: %s',
                                  machine)
                        unlock_one(machine, user)
                    ok_machs = do_update_keys(list(ok_machs.keys()))[1]
                update_nodes(ok_machs)
                return ok_machs
            elif reimage and machine_type in reimage_types:
                return reimage_machines(ctx, machines, machine_type)
            return machines
        elif response.status_code == 503:
            log.error('Insufficient nodes available to lock %d %s nodes.',
                      num, machine_type)
            log.error(response.text)
        else:
            log.error('Could not lock %d %s nodes, reason: unknown.',
                      num, machine_type)
    return []


def lock_one(name, user=None, description=None):
    name = misc.canonicalize_hostname(name, user=None)
    if user is None:
        user = misc.get_user()
    request = dict(name=name, locked=True, locked_by=user,
                   description=description)
    uri = os.path.join(config.lock_server, 'nodes', name, 'lock', '')
    response = requests.put(uri, json.dumps(request))
    success = response.ok
    if success:
        log.debug('locked %s as %s', name, user)
    else:
        try:
            reason = response.json().get('message')
        except ValueError:
            reason = str(response.status_code)
        log.error('failed to lock {node}. reason: {reason}'.format(
            node=name, reason=reason))
    return response


def unlock_safe(names: List[str], owner: str):
    with teuthology.parallel.parallel() as p:
        for name in names:
            p.spawn(unlock_one_safe, name, owner)
        return all(p)


def unlock_one_safe(name: str, owner: str) -> bool:
    node_status = query.get_status(name)
    if node_status.get("locked", False) is False:
        log.debug(f"Refusing to unlock {name} since it is already unlocked")
        return False
    maybe_job = query.node_active_job(name, node_status)
    if not maybe_job:
        return unlock_one(name, owner, node_status["description"], node_status)
    log.warning(f"Refusing to unlock {name} since it has an active job: {maybe_job}")
    return False


def unlock_many(names: List[str], owner: str):
    fixed_names = [misc.canonicalize_hostname(name, user=None) for name in
                   names]
    names = fixed_names
    uri = os.path.join(config.lock_server, 'nodes', 'unlock_many', '')
    data = dict(
        locked_by=owner,
        names=names,
    )
    with safe_while(
            sleep=1, increment=0.5, action=f'unlock_many {names}') as proceed:
        while proceed():
            response = requests.post(
                uri,
                data=json.dumps(data),
                headers={'content-type': 'application/json'},
            )
            if response.ok:
                log.debug("Unlocked: %s", ', '.join(names))
                return True
    log.error("Failed to unlock: %s", ', '.join(names))
    return False


def unlock_one(name, user, description=None, status: Union[dict, None] = None) -> bool:
    name = misc.canonicalize_hostname(name, user=None)
    if not description and status:
        description = status["description"]
    if not teuthology.provision.destroy_if_vm(name, user, description or ""):
        log.error('destroy failed for %s', name)
        return False
    # we're trying to stop node before actual unlocking
    status_info = teuthology.lock.query.get_status(name)
    try:
        if not teuthology.lock.query.is_vm(status=status_info):
            stop_node(name, status)
    except Exception:
        log.exception(f"Failed to stop {name}!")
    request = dict(name=name, locked=False, locked_by=user,
                   description=description)
    uri = os.path.join(config.lock_server, 'nodes', name, 'lock', '')
    with safe_while(
            sleep=1, increment=0.5, action="unlock %s" % name) as proceed:
        while proceed():
            try:
                response = requests.put(uri, json.dumps(request))
                if response.ok:
                    log.info('unlocked: %s', name)
                    return response.ok
                if response.status_code == 403:
                    break
            # Work around https://github.com/kennethreitz/requests/issues/2364
            except requests.ConnectionError as e:
                log.warning("Saw %s while unlocking; retrying...", str(e))
    try:
        reason = response.json().get('message')
    except ValueError:
        reason = str(response.status_code)
    log.error('failed to unlock {node}. reason: {reason}'.format(
        node=name, reason=reason))
    return False


def update_lock(name, description=None, status=None, ssh_pub_key=None):
    name = misc.canonicalize_hostname(name, user=None)
    updated = {}
    if description is not None:
        updated['description'] = description
    if status is not None:
        updated['up'] = (status == 'up')
    if ssh_pub_key is not None:
        updated['ssh_pub_key'] = ssh_pub_key

    if updated:
        uri = os.path.join(config.lock_server, 'nodes', name, '')
        inc = random.uniform(0, 1)
        with safe_while(
                sleep=1, increment=inc, action=f'update lock {name}') as proceed:
            while proceed():
                response = requests.put(
                    uri,
                    json.dumps(updated))
                if response.ok:
                    return True
        return response.ok
    return True


def update_inventory(node_dict):
    """
    Like update_lock(), but takes a dict and doesn't try to do anything smart
    by itself
    """
    name = node_dict.get('name')
    if not name:
        raise ValueError("must specify name")
    if not config.lock_server:
        return
    uri = os.path.join(config.lock_server, 'nodes', name, '')
    log.info("Updating %s on lock server", name)
    inc = random.uniform(0, 1)
    with safe_while(
            sleep=1, increment=inc, action=f'update inventory {name}') as proceed:
        while proceed():
            response = requests.put(
                uri,
                json.dumps(node_dict),
                headers={'content-type': 'application/json'},
            )
            if response.status_code == 404:
                log.info("Creating new node %s on lock server", name)
                uri = os.path.join(config.lock_server, 'nodes', '')
                response = requests.post(
                    uri,
                    json.dumps(node_dict),
                    headers={'content-type': 'application/json'},
                )
            if response.ok:
                return

def do_update_keys(machines, all_=False, _raise=True):
    reference = query.list_locks(keyed_by_name=True)
    if all_:
        machines = reference.keys()
    keys_dict = misc.ssh_keyscan(machines, _raise=_raise)
    return push_new_keys(keys_dict, reference), keys_dict


def push_new_keys(keys_dict, reference):
    ret = 0
    for hostname, pubkey in keys_dict.items():
        log.info('Checking %s', hostname)
        if reference[hostname]['ssh_pub_key'] != pubkey:
            log.info('New key found. Updating...')
            if not update_lock(hostname, ssh_pub_key=pubkey):
                log.error('failed to update %s!', hostname)
                ret = 1
    return ret


def reimage_machines(ctx, machines, machine_type):
    reimage_types = teuthology.provision.get_reimage_types()
    if machine_type not in reimage_types:
        log.info(f"Skipping reimage of {machines.keys()} because {machine_type} is not in {reimage_types}")
        return machines
    # Setup log file, reimage machines and update their keys
    reimaged = dict()
    console_log_conf = dict(
        logfile_name='{shortname}_reimage.log',
        remotes=[teuthology.orchestra.remote.Remote(machine)
                 for machine in machines],
    )
    with console_log.task(ctx, console_log_conf):
        with teuthology.parallel.parallel() as p:
            for machine in machines:
                log.info("Start node '%s' reimaging", machine)
                update_nodes([machine], True)
                p.spawn(teuthology.provision.reimage, ctx,
                        machine, machine_type)
                reimaged[machine] = machines[machine]
    reimaged = do_update_keys(list(reimaged.keys()))[1]
    update_nodes(reimaged)
    return reimaged


def block_and_lock_machines(ctx, total_requested, machine_type, reimage=True, tries=10):
    # It's OK for os_type and os_version to be None here.  If we're trying
    # to lock a bare metal machine, we'll take whatever is available.  If
    # we want a vps, defaults will be provided by misc.get_distro and
    # misc.get_distro_version in provision.create_if_vm
    os_type = ctx.config.get("os_type")
    os_version = ctx.config.get("os_version")
    arch = ctx.config.get('arch')
    reserved = config.reserve_machines
    assert isinstance(reserved, int), 'reserve_machines must be integer'
    assert (reserved >= 0), 'reserve_machines should >= 0'

    log.info('Locking machines...')
    # change the status during the locking process
    report.try_push_job_info(ctx.config, dict(status='waiting'))

    all_locked = dict()
    requested = total_requested
    while True:
        # get a candidate list of machines
        machines = query.list_locks(
            machine_type=machine_type,
            up=True,
            locked=False,
            count=requested + reserved,
            tries=tries,
        )
        if machines is None:
            if ctx.block:
                log.error('Error listing machines, trying again')
                time.sleep(20)
                continue
            else:
                raise RuntimeError('Error listing machines')

        # make sure there are machines for non-automated jobs to run
        if len(machines) < reserved + requested \
                and ctx.owner.startswith('scheduled'):
            if ctx.block:
                log.info(
                    'waiting for more %s machines to be free (need %s + %s, have %s)...',
                    machine_type,
                    reserved,
                    requested,
                    len(machines),
                )
                time.sleep(10)
                continue
            else:
                assert 0, ('not enough machines free; need %s + %s, have %s' %
                           (reserved, requested, len(machines)))

        try:
            newly_locked = lock_many(ctx, requested, machine_type,
                                     ctx.owner, ctx.archive, os_type,
                                     os_version, arch, reimage=reimage)
        except Exception:
            # Lock failures should map to the 'dead' status instead of 'fail'
            if 'summary' in ctx:
                set_status(ctx.summary, 'dead')
            raise
        all_locked.update(newly_locked)
        log.info(
            '{newly_locked} {mtype} machines locked this try, '
            '{total_locked}/{total_requested} locked so far'.format(
                newly_locked=len(newly_locked),
                mtype=machine_type,
                total_locked=len(all_locked),
                total_requested=total_requested,
            )
        )
        if len(all_locked) == total_requested:
            vmlist = []
            for lmach in all_locked:
                if query.is_vm(lmach):
                    vmlist.append(lmach)
            if vmlist:
                log.info('Waiting for virtual machines to come up')
                keys_dict = dict()
                loopcount = 0
                while len(keys_dict) != len(vmlist):
                    loopcount += 1
                    time.sleep(10)
                    keys_dict = misc.ssh_keyscan(vmlist)
                    if loopcount == 40:
                        loopcount = 0
                        log.info('virtual machine(s) still not up, ' +
                                 'recreating unresponsive ones.')
                        for guest in vmlist:
                            if guest not in keys_dict.keys():
                                log.info('recreating: ' + guest)
                                full_name = misc.canonicalize_hostname(guest)
                                teuthology.provision.destroy_if_vm(full_name)
                                teuthology.provision.create_if_vm(ctx, full_name)
                if do_update_keys(keys_dict)[0]:
                    log.info("Error in virtual machine keys")
                newscandict = {}
                for dkey in all_locked.keys():
                    stats = query.get_status(dkey)
                    newscandict[dkey] = stats['ssh_pub_key']
                ctx.config['targets'] = newscandict
            else:
                ctx.config['targets'] = all_locked
            locked_targets = yaml.safe_dump(
                ctx.config['targets'],
                default_flow_style=False
            ).splitlines()
            log.info('\n  '.join(['Locked targets:', ] + locked_targets))
            # successfully locked machines, change status back to running
            report.try_push_job_info(ctx.config, dict(status='running'))
            break
        elif not ctx.block:
            assert 0, 'not enough machines are available'
        else:
            requested = requested - len(newly_locked)
            assert requested > 0, "lock_machines: requested counter went" \
                                  "negative, this shouldn't happen"

        log.info(
            "{total} machines locked ({new} new); need {more} more".format(
                total=len(all_locked), new=len(newly_locked), more=requested)
        )
        log.warning('Could not lock enough machines, waiting...')
        time.sleep(10)


def stop_node(name: str, status: Union[dict, None]):
    status = status or query.get_status(name)
    remote_ = remote.Remote(name)
    if status['machine_type'] in provision.fog.get_types():
        remote_.console.power_off()
        return
    elif status['machine_type'] in provision.pelagos.get_types():
        provision.pelagos.park_node(name)
        return
    elif remote_.is_container:
        remote_.run(
            args=['sudo', '/testnode_stop.sh'],
            check_status=False,
        )
        return
