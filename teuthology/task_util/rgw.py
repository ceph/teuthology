from cStringIO import StringIO
import logging
import json
import requests
from urlparse import urlparse

from ..orchestra.connection import split_user
from teuthology import misc as teuthology

log = logging.getLogger(__name__)

def rgwadmin(ctx, client, cmd, stdin=StringIO(), check_status=False):
    log.info('rgwadmin: %s' % cmd)
    testdir = teuthology.get_testdir(ctx)
    pre = [
        '{tdir}/adjust-ulimits'.format(tdir=testdir),
        'ceph-coverage'.format(tdir=testdir),
        '{tdir}/archive/coverage'.format(tdir=testdir),
        'radosgw-admin'.format(tdir=testdir),
        '--log-to-stderr',
        '--format', 'json',
        '-n',  client,
        ]
    pre.extend(cmd)
    log.info('rgwadmin: cmd=%s' % pre)
    (remote,) = ctx.cluster.only(client).remotes.iterkeys()
    proc = remote.run(
        args=pre,
        check_status=check_status,
        stdout=StringIO(),
        stderr=StringIO(),
        stdin=stdin,
        )
    r = proc.exitstatus
    out = proc.stdout.getvalue()
    j = None
    if not r and out != '':
        try:
            j = json.loads(out)
            log.info(' json result: %s' % j)
        except ValueError:
            j = out
            log.info(' raw result: %s' % j)
    return (r, j)

def get_zone_host_and_port(ctx, client, zone):
    _, region_map = rgwadmin(ctx, client, check_status=True,
                             cmd=['-n', client, 'region-map', 'get'])
    regions = region_map['regions']
    for region in regions:
        for zone_info in region['val']['zones']:
            if zone_info['name'] == zone:
                endpoint = urlparse(zone_info['endpoints'][0])
                host, port = endpoint.hostname, endpoint.port
                if port is None:
                    port = 80
                return host, port
    assert False, 'no endpoint for zone {zone} found'.format(zone=zone)

def get_master_zone(ctx, client):
    _, region_map = rgwadmin(ctx, client, check_status=True,
                             cmd=['-n', client, 'region-map', 'get'])
    regions = region_map['regions']
    for region in regions:
        is_master = (region['val']['is_master'] == "true")
        log.info('region={r} is_master={ism}'.format(r=region, ism=is_master))
        if not is_master:
          continue
        master_zone = region['val']['master_zone']
        log.info('master_zone=%s' % master_zone)
        for zone_info in region['val']['zones']:
            if zone_info['name'] == master_zone:
                return master_zone
    log.info('couldn\'t find master zone')
    return None

def get_master_client(ctx, clients):
    master_zone = get_master_zone(ctx, clients[0]) # can use any client for this as long as system configured correctly
    if not master_zone:
        return None

    for client in clients:
        zone = zone_for_client(ctx, client)
        if zone == master_zone:
            return client

    return None

def get_zone_system_keys(ctx, client, zone):
    _, zone_info = rgwadmin(ctx, client, check_status=True,
                            cmd=['-n', client,
                                 'zone', 'get', '--rgw-zone', zone])
    system_key = zone_info['system_key']
    return system_key['access_key'], system_key['secret_key']

def zone_for_client(ctx, client):
    ceph_config = ctx.ceph.conf.get('global', {})
    ceph_config.update(ctx.ceph.conf.get('client', {}))
    ceph_config.update(ctx.ceph.conf.get(client, {}))
    return ceph_config.get('rgw zone')


def radosgw_agent_sync(ctx, agent_host, agent_port):
    log.info('sync agent {h}:{p}'.format(h=agent_host, p=agent_port))
    return requests.post('http://{addr}:{port}/metadata/incremental'.format(addr = agent_host, port = agent_port))

def radosgw_agent_sync_all(ctx):
    if ctx.radosgw_agent.procs:
        for agent_client, c_config in ctx.radosgw_agent.config.iteritems():
            dest_zone = zone_for_client(ctx, agent_client)
            sync_dest, sync_port = get_sync_agent(ctx, agent_client)
            log.debug('doing a sync from {host1} to {host2}'.format(
                host1=agent_client,host2=sync_dest))
            radosgw_agent_sync(ctx, sync_dest, sync_port)

def host_for_role(ctx, role):
    for target, roles in zip(ctx.config['targets'].iterkeys(), ctx.config['roles']):
        if role in roles:
            _, host = split_user(target)
            return host

def get_sync_agent(ctx, source):
    for task in ctx.config['tasks']:
        if 'radosgw-agent' not in task:
            continue
        for client, conf in task['radosgw-agent'].iteritems():
            if conf['src'] == source:
                return host_for_role(ctx, source), conf.get('port', 8000)
    return None, None
