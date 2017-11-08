import logging
import time
try:
    import libvirt
except ImportError:
    libvirt = None

import teuthology.lock.query
import teuthology.lock.util

log = logging.getLogger(__name__)


class VirtualConsole():
    """
    Virtual Console (set from getRemoteConsole)
    """
    def __init__(self, name):
        if libvirt is None:
            raise RuntimeError("libvirt not found")

        self.shortname = remote.getShortName(name)
        status_info = teuthology.lock.query.get_status(self.shortname)
        try:
            if teuthology.lock.query.is_vm(status=status_info):
                phys_host = status_info['vm_host']['name'].split('.')[0]
        except TypeError:
            raise RuntimeError("Cannot create a virtual console for %s", name)
        self.connection = libvirt.open(phys_host)
        for i in self.connection.listDomainsID():
            d = self.connection.lookupByID(i)
            if d.name() == self.shortname:
                self.vm_domain = d
                break
        return

    def check_power(self, state, timeout=None):
        """
        Return true if vm domain state indicates power is on.
        """
        return self.vm_domain.info[0] in [libvirt.VIR_DOMAIN_RUNNING,
                                          libvirt.VIR_DOMAIN_BLOCKED,
                                          libvirt.VIR_DOMAIN_PAUSED]

    def check_status(self, timeout=None):
        """
        Return true if running.
        """
        return self.vm_domain.info()[0] == libvirt.VIR_DOMAIN_RUNNING

    def power_cycle(self):
        """
        Simiulate virtual machine power cycle
        """
        self.vm_domain.info().destroy()
        self.vm_domain.info().create()

    def hard_reset(self):
        """
        Simiulate hard reset
        """
        self.vm_domain.info().destroy()

    def power_on(self):
        """
        Simiulate power on
        """
        self.vm_domain.info().create()

    def power_off(self):
        """
        Simiulate power off
        """
        self.vm_domain.info().destroy()

    def power_off_for_interval(self, interval=30):
        """
        Simiulate power off for an interval.
        """
        log.info('Power off {s} for {i} seconds'.format(
            s=self.shortname, i=interval))
        self.vm_domain.info().destroy()
        time.sleep(interval)
        self.vm_domain.info().create()
        log.info('Power off for {i} seconds completed'.format(
            s=self.shortname, i=interval))
