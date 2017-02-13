import logging
import StringIO

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

    def __init__(self, ctx, config):
        self._remotes = ctx.cluster.remotes
        self._teuthology_ip_address = None

    @property
    def remotes(self):
        return self._remotes

    @property
    def teuthology_ip_address(self):
        """Return the IP address of the teuthology VM"""
        if self._teuthology_ip_address is None:
            # FIXME: this seems fragile (ens3 hardcoded)
            self._teuthology_ip_address = ifaddresses('ens3')[2][0]['addr']
        return self._teuthology_ip_address

    @property
    def teuthology_fqdn(self):
        """Return the resolvable FQDN of the teuthology VM"""
        ip_addr = self.teuthology_ip_address.split('.')
        log.debug("teuthology_ip_address returned {}".format(ip_addr))
        return "target{:03d}{:03d}{:03d}{:03d}.teuthology".format(
            int(ip_addr[0]),
            int(ip_addr[1]),
            int(ip_addr[2]),
            int(ip_addr[3]),
        )

    def generate_minion_keys(self):
        for rem in self.remotes.iterkeys():
            mfqdn=rem.name.split('@')[1]
            minion_id=rem.shortname
            log.debug("minion: FQDN {fqdn}, ID {sn}".format(
                fqdn=mfqdn,
                sn=minion_id,
            ))
            if isfile('{sn}.pub'.format(sn=minion_id)):
                log.debug("{sn} minion key already set up".format(sn=minion_id))
                continue
            sh('sudo salt-key --gen-keys={sn}'.format(sn=minion_id))

    def cleanup_keys(self):
        for rem in self.remotes.iterkeys():
            mfqdn=rem.name.split('@')[1]
            minion_id=rem.shortname
            log.debug("minion: FQDN {fqdn}, ID {sn}".format(
                fqdn=mfqdn,
                sn=minion_id,
            ))
            sh('sudo salt-key -y -d {sn}'.format(sn=minion_id))

    def set_master_fqdn(self, master_fqdn):
        """Ensures master_fqdn is not None"""
        if master_fqdn is None:
            master_fqdn = self.teuthology_fqdn
        return master_fqdn

    def preseed_minions(self, master_fqdn=None):
        master_fqdn = self.set_master_fqdn(master_fqdn)
        for rem in self.remotes.iterkeys():
            mfqdn=rem.name.split('@')[1]
            minion_id=rem.shortname
            if master_fqdn == self.teuthology_fqdn:
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
                stdout=StringIO.StringIO()
            )
            log.debug("{fqdn} reports: {output}".format(
                fqdn=mfqdn,
                output=r.stdout.getvalue(),
            ))

    def set_minion_master(self, master_fqdn=None):
        """Points all minions to the given master"""
        master_fqdn = self.set_master_fqdn(master_fqdn)
        for rem in self.remotes.iterkeys():
            sed_cmd = 'echo master: {} > /etc/salt/minion.d/master.conf'.format(master_fqdn)
            rem.run(args=[
                'sudo',
                'sh',
                '-c',
                sed_cmd,
            ])

    def start_master(self, master_fqdn=None):
        """Starts salt-master.service on given FQDN via SSH"""
        master_fqdn = self.set_master_fqdn(master_fqdn)
        sh('ssh {} sudo systemctl restart salt-master.service'.format(
            master_fqdn
        ))

    def stop_minions(self, ctx):
        """Stops salt-minion.service on all target VMs"""
        run.wait(
            ctx.cluster.run(
                args=['sudo', 'systemctl', 'stop', 'salt-minion.service'],
                wait=False,
            )
        )

    def start_minions(self, ctx):
        """Starts salt-minion.service on all target VMs"""
        run.wait(
            ctx.cluster.run(
                args=['sudo', 'systemctl', 'start', 'salt-minion.service'],
                wait=False,
            )
        )

