import logging
import pexpect
import time

from teuthology.config import config
from teuthology.orchestra.console.base import Console, NoConserver

log = logging.getLogger(__name__)


class PhysicalConsole(Console):
    """
    Physical Console (set from getRemoteConsole)
    """
    def __init__(self, name, ipmiuser=None, ipmipass=None, ipmidomain=None,
                 logfile=None, timeout=20):
        super(PhysicalConsole, self).__init__(
            name, timeout=timeout, logfile=logfile)
        self.ipmiuser = ipmiuser or config.ipmi_user
        self.ipmipass = ipmipass or config.ipmi_password
        self.ipmidomain = ipmidomain or config.ipmi_domain
        self.has_ipmi_credentials = all(
            [self.ipmiuser, self.ipmipass, self.ipmidomain]
        )

    def _pexpect_spawn_ipmi(self, ipmi_cmd):
        """
        Run the cmd specified using ipmitool.
        """
        full_command = self._ipmi_command(ipmi_cmd)
        return self._pexpect_spawn(full_command)

    def _get_console(self, readonly=True):
        child = super(PhysicalConsole, self)._get_console(
            readonly=readonly,
        )
        if self.has_conserver and not child.isalive():
            log.error("conserver failed to get the console; will try ipmitool")
            self.has_conserver = False
            child = super(PhysicalConsole, self)._get_console(
                readonly=readonly,
            )
        return child

    def _console_command(self, readonly=True):
        try:
            return super(PhysicalConsole, self)._console_command(
                readonly=readonly,
            )
        except NoConserver:
            return self._ipmi_command('sol activate')

    def _ipmi_command(self, subcommand):
        self._check_ipmi_credentials()
        template = \
            'ipmitool -H {s}.{dn} -I lanplus -U {ipmiuser} -P {ipmipass} {cmd}'
        return template.format(
            cmd=subcommand,
            s=self.shortname,
            dn=self.ipmidomain,
            ipmiuser=self.ipmiuser,
            ipmipass=self.ipmipass,
        )

    def _check_ipmi_credentials(self):
        if not self.has_ipmi_credentials:
            log.error(
                "Must set ipmi_user, ipmi_password, and ipmi_domain in "
                ".teuthology.yaml"
            )

    def _exit_session(self, child, timeout=None):
        t = timeout or self.timeout
        try:
            super(PhysicalConsole, self)._exit_session(
                child, timeout=timeout)
        except NoConserver:
            child.send('~.')
            r = child.expect(
                ['terminated ipmitool', pexpect.TIMEOUT, pexpect.EOF],
                timeout=t)
            if r != 0:
                self._pexpect_spawn_ipmi('sol deactivate')

    def check_power(self, state, timeout=None):
        """
        Check power.  Retry if EOF encountered on power check read.
        """
        timeout = timeout or self.timeout
        t = 1
        total = t
        ta = time.time()
        while total < timeout:
            c = self._pexpect_spawn_ipmi('power status')
            r = c.expect(['Chassis Power is {s}'.format(
                s=state), pexpect.EOF, pexpect.TIMEOUT], timeout=t)
            tb = time.time()
            if r == 0:
                return True
            elif r == 1:
                # keep trying if EOF is reached, first sleep for remaining
                # timeout interval
                if tb - ta < t:
                    time.sleep(t - (tb - ta))
            # go around again if EOF or TIMEOUT
            ta = tb
            t *= 2
            total += t
        return False

    def check_status(self, timeout=None):
        """
        Check status.  Returns True if console is at login prompt
        """
        try:
            # check for login prompt at console
            self._wait_for_login(timeout)
            return True
        except Exception as e:
            log.info('Failed to get ipmi console status for {s}: {e}'.format(
                s=self.shortname, e=e))
            return False

    def power_cycle(self):
        """
        Power cycle and wait for login.
        """
        log.info('Power cycling {s}'.format(s=self.shortname))
        child = self._pexpect_spawn_ipmi('power cycle')
        child.expect('Chassis Power Control: Cycle', timeout=self.timeout)
        self._wait_for_login(timeout=300)
        log.info('Power cycle for {s} completed'.format(s=self.shortname))

    def hard_reset(self):
        """
        Perform physical hard reset.  Retry if EOF returned from read
        and wait for login when complete.
        """
        log.info('Performing hard reset of {s}'.format(s=self.shortname))
        start = time.time()
        while time.time() - start < self.timeout:
            child = self._pexpect_spawn_ipmi('power reset')
            r = child.expect(['Chassis Power Control: Reset', pexpect.EOF],
                             timeout=self.timeout)
            if r == 0:
                break
        self._wait_for_login()
        log.info('Hard reset for {s} completed'.format(s=self.shortname))

    def power_on(self):
        """
        Physical power on.  Loop checking cmd return.
        """
        log.info('Power on {s}'.format(s=self.shortname))
        start = time.time()
        while time.time() - start < self.timeout:
            child = self._pexpect_spawn_ipmi('power on')
            r = child.expect(['Chassis Power Control: Up/On', pexpect.EOF],
                             timeout=self.timeout)
            if r == 0:
                break
        if not self.check_power('on'):
            log.error('Failed to power on {s}'.format(s=self.shortname))
        log.info('Power on for {s} completed'.format(s=self.shortname))

    def power_off(self):
        """
        Physical power off.  Loop checking cmd return.
        """
        log.info('Power off {s}'.format(s=self.shortname))
        start = time.time()
        while time.time() - start < self.timeout:
            child = self._pexpect_spawn_ipmi('power off')
            r = child.expect(['Chassis Power Control: Down/Off', pexpect.EOF],
                             timeout=self.timeout)
            if r == 0:
                break
        if not self.check_power('off', 60):
            log.error('Failed to power off {s}'.format(s=self.shortname))
        log.info('Power off for {s} completed'.format(s=self.shortname))

    def power_off_for_interval(self, interval=30):
        """
        Physical power off for an interval. Wait for login when complete.

        :param interval: Length of power-off period.
        """
        log.info('Power off {s} for {i} seconds'.format(
            s=self.shortname, i=interval))
        child = self._pexpect_spawn_ipmi('power off')
        child.expect('Chassis Power Control: Down/Off', timeout=self.timeout)

        time.sleep(interval)

        child = self._pexpect_spawn_ipmi('power on')
        child.expect('Chassis Power Control: Up/On', timeout=self.timeout)
        self._wait_for_login()
        log.info('Power off for {i} seconds completed'.format(
            s=self.shortname, i=interval))

    def spawn_sol_log(self, dest_path):
        proc = super(PhysicalConsole, self).spawn_sol_log(dest_path)
        if self.has_conserver and proc.poll() is not None:
            log.error("conserver failed to get the console; will try ipmitool")
            self.has_conserver = False
            proc = super(PhysicalConsole, self).spawn_sol_log(dest_path)
        return proc
