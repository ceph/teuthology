import io
import logging
import os
import pexpect
import psutil
import subprocess
import sys
import time

from typing import Union, Literal, Optional

import teuthology.lock.query
import teuthology.lock.util
from teuthology.config import config
from teuthology.contextutil import safe_while
from teuthology.exceptions import ConsoleError
from teuthology.misc import host_shortname

try:
    import libvirt
except ImportError:
    libvirt = None

log = logging.getLogger(__name__)
PowerOnOffState = Union[Literal["on"], Literal["off"]]


class RemoteConsole():
    def getShortName(self, name=None):
        """
        Extract the name portion from remote name strings.
        """
        hostname = (name or self.name).split('@')[-1]
        return host_shortname(hostname)


class PhysicalConsole(RemoteConsole):
    """
    Physical Console (set from getRemoteConsole)
    """
    def __init__(self, name, ipmiuser=None, ipmipass=None, ipmidomain=None,
                 timeout=120):
        self.name = name
        self.shortname = self.getShortName(name)
        self.log = log.getChild(self.shortname)
        self.timeout = timeout
        self.ipmiuser = ipmiuser or config.ipmi_user
        self.ipmipass = ipmipass or config.ipmi_password
        self.ipmidomain = ipmidomain or config.ipmi_domain
        self.has_ipmi_credentials = all(
            [self.ipmiuser, self.ipmipass, self.ipmidomain]
        )
        self.conserver_master = config.conserver_master
        self.conserver_port = config.conserver_port
        conserver_client_found = psutil.Popen(
            'which console',
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT).wait() == 0
        self.has_conserver = all([
            config.use_conserver is not False,
            self.conserver_master,
            self.conserver_port,
            conserver_client_found,
        ])

    def _pexpect_spawn_ipmi(self, ipmi_cmd):
        """
        Run the cmd specified using ipmitool.
        """
        full_command = self._ipmi_command(ipmi_cmd)
        return self._pexpect_spawn(full_command)

    def _pexpect_spawn(self, cmd):
        """
        Run a command using pexpect.spawn(). Return the child object.
        """
        self.log.debug('pexpect command: %s', cmd)
        p = pexpect.spawn(
            cmd,
            encoding='utf-8',
            codec_errors="backslashreplace",
        )
        p.logfile_read = io.StringIO()
        return p

    def _get_console(self, readonly=True):
        def start():
            cmd = self._console_command(readonly=readonly)
            return self._pexpect_spawn(cmd)

        child = start()
        if self.has_conserver and not child.isalive():
            self.log.error("conserver failed to get the console; will try ipmitool")
            self.has_conserver = False
            child = start()
        return child

    def _console_command(self, readonly=True):
        if self.has_conserver:
            return 'console -M {master} -p {port} {mode} {host}'.format(
                master=self.conserver_master,
                port=self.conserver_port,
                mode='-s' if readonly else '-f',
                host=self.shortname,
            )
        else:
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
            self.log.error(
                "Must set ipmi_user, ipmi_password, and ipmi_domain in "
                ".teuthology.yaml"
            )

    def _exit_session(self, child, timeout=None):
        t = timeout or self.timeout
        if self.has_conserver:
            child.sendcontrol('e')
            child.send('c.')
            r = child.expect(
                ['[disconnect]', pexpect.TIMEOUT, pexpect.EOF],
                timeout=t)
            if r != 0:
                child.kill(15)
            self.log.debug('console disconnect output: %s', child.logfile_read.getvalue().strip())
        else:
            child.send('~.')
            r = child.expect(
                ['terminated ipmitool', pexpect.TIMEOUT, pexpect.EOF],
                timeout=t)
            self.log.debug('ipmitool disconnect output: %s', child.logfile_read.getvalue().strip())
            if r != 0:
                self._pexpect_spawn_ipmi('sol deactivate')
                self.log.debug('sol deactivate output: %s', child.logfile_read.getvalue().strip())

    def _wait_for_login(self, timeout=None, attempts=2):
        """
        Wait for login.  Retry if timeouts occur on commands.
        """
        t = timeout or self.timeout
        self.log.debug('Waiting for login prompt')
        # wait for login prompt to indicate boot completed
        for i in range(0, attempts):
            start = time.time()
            while time.time() - start < t:
                child = self._get_console(readonly=False)
                child.send('\n')
                r = child.expect(
                    ['{s} login: '.format(s=self.shortname),
                     pexpect.TIMEOUT,
                     pexpect.EOF],
                    timeout=(t - (time.time() - start)))
                self.log.debug('expect before: {b}'.format(b=child.before))
                self.log.debug('expect after: {a}'.format(a=child.after))

                self._exit_session(child)
                if r == 0:
                    return
        raise ConsoleError("Did not get a login prompt from %s!" % self.name)

    def check_power(self, state: Literal["on","off"]):
        c = self._pexpect_spawn_ipmi('power status')
        r = c.expect(['Chassis Power is {s}'.format(
            s=state), pexpect.EOF, pexpect.TIMEOUT], timeout=1)
        self.log.debug('check power output: %s', c.logfile_read.getvalue().strip())
        return r == 0

    def set_power(self, state: PowerOnOffState, timeout: Optional[int]):
        self.log.info(f"Power {state}")
        timeout = timeout or self.timeout
        sleep_time = 4
        reissue_after_failures = 5
        failures = 0
        issued = False
        succeeded = False
        with safe_while(
                sleep=sleep_time,
                tries=int(timeout / sleep_time),
                _raise=False,
                action='wait for power on') as proceed:
            while proceed():
                if not issued:
                    child = self._pexpect_spawn_ipmi(f"power {state}")
                    rc = child.expect(
                        [
                            "Up/On" if state.lower() == "on" else "Down/Off",
                            pexpect.EOF
                        ],
                        timeout=self.timeout
                    )
                    self.log.debug(
                        f"power {state} output: {child.logfile_read.getvalue().strip()}"
                    )
                    if rc == 0:
                        issued = True
                    continue

                if not succeeded:
                    child = self._pexpect_spawn_ipmi('power status')
                    rc = child.expect(
                        [
                            f"Chassis Power is {state}",
                            pexpect.EOF,
                            pexpect.TIMEOUT
                        ],
                        timeout=1
                    )
                    self.log.debug(
                        f"check power output: {child.logfile_read.getvalue().strip()}"
                    )
                    if rc == 0:
                        succeeded = True
                        break
                    failures += 1
                    if failures == reissue_after_failures:
                        issued = False

        if issued and succeeded:
            self.log.info(f"Power {state} completed")
            return True
        raise RuntimeError(
            f"Failed to power {state} {self.shortname} in {self.timeout}s"
        )
        return False

    def check_power_retries(self, state, timeout=None):
        """
        Check power.  Retry if EOF encountered on power check read.
        """
        timeout = timeout or self.timeout
        sleep_time = 4.0
        with safe_while(
                sleep=sleep_time,
                tries=int(timeout / sleep_time),
                _raise=False,
                action='wait for power %s' % state) as proceed:
            while proceed():
                c = self._pexpect_spawn_ipmi('power status')
                r = c.expect(['Chassis Power is {s}'.format(
                    s=state), pexpect.EOF, pexpect.TIMEOUT], timeout=1)
                self.log.debug('check power output: %s', c.logfile_read.getvalue().strip())
                if r == 0:
                    return True
        return False

    def check_status(self, timeout=None):
        """
        Check status.  Returns True if console is at login prompt
        """
        try:
            # check for login prompt at console
            self._wait_for_login(timeout)
            return True
        except Exception:
            self.log.exception('Failed to get ipmi console status')
            return False

    def power_cycle(self, timeout=300):
        """
        Power cycle and wait for login.

        :param timeout: How long to wait for login
        """
        self.log.info('Power cycling')
        child = self._pexpect_spawn_ipmi('power cycle')
        child.expect('Chassis Power Control: Cycle', timeout=self.timeout)
        self.log.debug('power cycle output: %s', child.logfile_read.getvalue().strip())
        self._wait_for_login(timeout=timeout)
        self.log.info('Power cycle completed')

    def hard_reset(self, wait_for_login=True):
        """
        Perform physical hard reset.  Retry if EOF returned from read
        and wait for login when complete.
        """
        self.log.info('Performing hard reset')
        start = time.time()
        while time.time() - start < self.timeout:
            child = self._pexpect_spawn_ipmi('power reset')
            r = child.expect(['Chassis Power Control: Reset', pexpect.EOF],
                             timeout=self.timeout)
            self.log.debug('power reset output: %s', child.logfile_read.getvalue().strip())
            if r == 0:
                break
        if wait_for_login:
            self._wait_for_login()
        self.log.info('Hard reset completed')

    def power_on(self):
        """
        Physical power on.  Loop checking cmd return.
        """
        return self.set_power("on", timeout=None)

    def power_off(self):
        """
        Physical power off.  Loop checking cmd return.
        """
        try:
            return self.set_power("off", timeout=None)
        except Exception:
            pass

    def power_off_for_interval(self, interval=30):
        """
        Physical power off for an interval. Wait for login when complete.

        :param interval: Length of power-off period.
        """
        self.log.info('Power off for {i} seconds'.format(i=interval))
        child = self._pexpect_spawn_ipmi('power off')
        child.expect('Chassis Power Control: Down/Off', timeout=self.timeout)

        self.log.debug('power off output: %s', child.logfile_read.getvalue().strip())
        child.logfile_read.seek(0)
        child.logfile_read.truncate()

        time.sleep(interval)

        child = self._pexpect_spawn_ipmi('power on')
        child.expect('Chassis Power Control: Up/On', timeout=self.timeout)
        self.log.debug('power on output: %s', child.logfile_read.getvalue().strip())
        self._wait_for_login()
        self.log.info('Power off for {i} seconds completed'.format(i=interval))

    def spawn_sol_log(self, dest_path):
        """
        Using the subprocess module, spawn an ipmitool process using 'sol
        activate' and redirect its output to a file.

        :returns: a psutil.Popen object
        """
        pexpect_templ = \
            "import pexpect; " \
            "pexpect.run('{cmd}', logfile=open('{log}', 'wb'), timeout=None)"

        def start():
            console_cmd = self._console_command()
            # use sys.executable to find python rather than /usr/bin/env.
            # The latter relies on PATH, which is set in a virtualenv
            # that's been activated, but is not set when binaries are
            # run directly from the virtualenv's bin/ directory.
            python_cmd = [
                sys.executable, '-c',
                pexpect_templ.format(
                    cmd=console_cmd,
                    log=dest_path,
                ),
            ]
            return psutil.Popen(
                python_cmd,
                env=os.environ,
            )

        proc = start()
        if self.has_conserver and proc.poll() is not None:
            self.log.error("conserver failed to get the console; will try ipmitool")
            self.has_conserver = False
            proc = start()
        return proc


class VirtualConsole(RemoteConsole):
    """
    Virtual Console (set from getRemoteConsole)
    """
    def __init__(self, name):
        if libvirt is None:
            raise RuntimeError("libvirt not found")

        self.shortname = self.getShortName(name)
        self.log = log.getChild(self.shortname)
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
        self.log.info('Power off for {i} seconds'.format(i=interval))
        self.vm_domain.info().destroy()
        time.sleep(interval)
        self.vm_domain.info().create()
        self.log.info('Power off for {i} seconds completed'.format(i=interval))
