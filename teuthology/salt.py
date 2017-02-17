import logging
import time

from os.path import isfile
from netifaces import ifaddresses

import teuthology
from .misc import sh
from .orchestra import run

log = logging.getLogger(__name__)


class UseSalt(object):

    def __init__(self, machine_type, os_type):
        self._machine_type = machine_type
        self._os_type = os_type

    @property
    def machine_type(self):
        return self._machine_type

    @property
    def os_type(self):
        return self._os_type

    @property
    def openstack(self):
        if self.machine_type == 'openstack':
            return True
        return False

    @property
    def suse(self):
        if self.os_type in ['opensuse', 'sle']:
            return True
        return False

    @property
    def use_salt(self):
        if self.openstack and self.suse:
            return True
        return False


class Salt(object):

    def __init__(self, ctx, config, **kwargs):
        self._ctx = ctx
        self._job_id = ctx.config.get('job_id')
        self._cluster = ctx.cluster
        self._remotes = ctx.cluster.remotes
        # FIXME: this seems fragile (ens3 hardcoded)
        self._teuthology_ip_address = ifaddresses('ens3')[2][0]['addr']
        self._minions = []
        ip_addr = self._teuthology_ip_address.split('.')
        self._teuthology_fqdn = "target{:03d}{:03d}{:03d}{:03d}.teuthology".format(
            int(ip_addr[0]),
            int(ip_addr[1]),
            int(ip_addr[2]),
            int(ip_addr[3]),
        )
        self._master_fqdn = kwargs.get('master_fqdn', self._teuthology_fqdn)

    @property
    def ctx(self):
        return self._ctx

    @property
    def job_id(self):
        """Name of the current teuthology run"""
        return self._job_id

    @property
    def remotes(self):
        return self._remotes

    @property
    def cluster(self):
        return self._cluster

    @property
    def master_fqdn(self):
        return self._master_fqdn

    @property
    def minions(self):
        """List of minion IDs"""
        return self._minions

    @property
    def teuthology_ip_address(self):
        """Return the IP address of the teuthology VM"""
        return self._teuthology_ip_address

    @property
    def teuthology_fqdn(self):
        """Return the resolvable FQDN of the teuthology VM"""
        return self._teuthology_fqdn

    def generate_minion_keys(self):
        for rem in self.remotes.iterkeys():
            minion_fqdn=rem.name.split('@')[1]
            minion_id=rem.shortname
            self._minions.append(minion_id)
            log.debug("minion: FQDN {fqdn}, ID {sn}".format(
                fqdn=minion_fqdn,
                sn=minion_id,
            ))
            if isfile('{sn}.pub'.format(sn=minion_id)):
                log.debug("{sn} minion key already set up".format(sn=minion_id))
                continue
            sh('sudo salt-key --gen-keys={sn}'.format(sn=minion_id))

    def cleanup_keys(self):
        for rem in self.remotes.iterkeys():
            minion_fqdn=rem.name.split('@')[1]
            minion_id=rem.shortname
            log.debug("Deleting minion key: FQDN {fqdn}, ID {sn}".format(
                fqdn=minion_fqdn,
                sn=minion_id,
            ))
            sh('sudo salt-key -y -d {sn}'.format(sn=minion_id))

    def preseed_minions(self):
        for rem in self.remotes.iterkeys():
            minion_fqdn=rem.name.split('@')[1]
            minion_id=rem.shortname
            if self.master_fqdn == self.teuthology_fqdn:
                sh('sudo cp {sn}.pub /etc/salt/pki/master/minions/{sn}'.format(
                    sn=minion_id)
                )
            else:
                # This case is for when master != teuthology...not important for
                # now
                pass
            keys = "{sn}.pem {sn}.pub".format(sn=minion_id)
            sh('sudo chown ubuntu {k}'.format(k=keys))
            sh('scp {k} {fn}:'.format(
                k=keys,
                fn=rem.name,
            ))
            r = rem.run(
                args=[
                    'sudo',
		    'sh',
                    '-c',
                    'echo "grains:" > /etc/salt/minion.d/job_id_grains.conf;\
                    echo "  job_id: {}" >> /etc/salt/minion.d/job_id_grains.conf'.format(self.job_id),
		    'sudo',
                    'chown',
                    'root',
                    '{}.pem'.format(minion_id),
                    '{}.pub'.format(minion_id),
                    run.Raw(';'),
                    'sudo',
                    'chmod',
                    '600',
                    '{}.pem'.format(minion_id),
                    '{}.pub'.format(minion_id),
                    run.Raw(';'),
                    'sudo',
                    'mv',
                    '{}.pem'.format(minion_id),
                    '/etc/salt/pki/minion/minion.pem',
                    run.Raw(';'),
                    'sudo',
                    'mv',
                    '{}.pub'.format(minion_id),
                    '/etc/salt/pki/minion/minion.pub',
                    run.Raw(';'),
                    'sudo',
                    'sh',
                    '-c',
                    'echo {} > /etc/salt/minion_id'.format(minion_id),
                    run.Raw(';'),
                    'sudo',
                    'cat',
                    '/etc/salt/minion_id',
                ],
            )

    def set_minion_master(self):
        """Points all minions to the master"""
        for rem in self.remotes.iterkeys():
            sed_cmd = 'echo master: {} > ' \
                      '/etc/salt/minion.d/master.conf'.format(
                self.master_fqdn
            )
            rem.run(args=[
                'sudo',
                'sh',
                '-c',
                sed_cmd,
            ])

    def init_minions(self):
        self.generate_minion_keys()
        self.preseed_minions()
        self.set_minion_master()

    def start_master(self):
        """Starts salt-master.service on given FQDN via SSH"""
        sh('ssh {} sudo systemctl restart salt-master.service'.format(
            self.master_fqdn
        ))

    def stop_minions(self):
        """Stops salt-minion.service on all target VMs"""
        run.wait(
            self.cluster.run(
                args=['sudo', 'systemctl', 'stop', 'salt-minion.service'],
                wait=False,
            )
        )

    def start_minions(self):
        """Starts salt-minion.service on all target VMs"""
        run.wait(
            self.cluster.run(
                args=['sudo', 'systemctl', 'start', 'salt-minion.service'],
                wait=False,
            )
        )

    def ping_minions_serial(self):
        """Pings minions, raises exception if they don't respond"""
        for mid in self.minions:
            for wl in range(10):
                time.sleep(5)
                log.debug("Attempt {n}/10 to ping Salt Minion {m}".format(
                    m=mid,
                    n=wl+1,
                ))
                if self.master_fqdn == self.teuthology_fqdn:
                    sh("sudo salt '{}' test.ping".format(mid))
                    # how do we determine success/failure?
                else:
                    # master is a remote
                    pass

    def ping_minions_parallel(self):
        """Pings minions, raises exception if they don't respond"""
        for wl in range(10):
            time.sleep(5)
            log.debug("Attempt {n}/10 to ping all Salt Minions in job {j}".format(
                j=self.job_id,
                n=wl+1,
            ))
            if self.master_fqdn == self.teuthology_fqdn:
                sh("sudo salt -C 'G@job_id:{}' test.ping".format(self.job_id))
                # how do we determine success/failure?
            else:
                # master is a remote
                pass

