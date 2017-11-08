import logging
import os
import pexpect
import psutil
import subprocess
import sys
import time

import teuthology.orchestra.remote

from teuthology.config import config
from teuthology.exceptions import ConsoleError

log = logging.getLogger(__name__)


class NoConserver(Exception):
    pass


class Console(object):
    """ Base console class. Only supports conserver operations. """
    def __init__(self, name, timeout=20, logfile=None):
        self.name = name
        self.shortname = teuthology.orchestra.remote.getShortName(name)
        self.timeout = timeout
        self.logfile = logfile
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

    def _console_command(self, readonly=True):
        if self.has_conserver:
            return 'console -M {master} -p {port} {mode} {host}'.format(
                master=self.conserver_master,
                port=self.conserver_port,
                mode='-s' if readonly else '-f',
                host=self.shortname,
            )
        else:
            raise NoConserver()

    def _pexpect_spawn(self, cmd):
        """
        Run a command using pexpect.spawn(). Return the child object.
        """
        log.debug('pexpect command: %s', cmd)
        return pexpect.spawn(
            cmd,
            logfile=self.logfile,
        )

    def _get_console(self, readonly=True):
        def start():
            cmd = self._console_command(readonly=readonly)
            return self._pexpect_spawn(cmd)
        child = start()
        return child

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
        else:
            raise NoConserver()

    def _wait_for_login(self, timeout=None, attempts=2):
        """
        Wait for login.  Retry if timeouts occur on commands.
        """
        t = timeout or self.timeout
        log.debug('Waiting for login prompt on {s}'.format(s=self.shortname))
        # wait for login prompt to indicate boot completed
        for i in range(0, attempts):
            start = time.time()
            while time.time() - start < t:
                child = self._get_console(readonly=False)
                child.send('\n')
                log.debug('expect: {s} login'.format(s=self.shortname))
                r = child.expect(
                    ['{s} login: '.format(s=self.shortname),
                     pexpect.TIMEOUT,
                     pexpect.EOF],
                    timeout=(t - (time.time() - start)))
                log.debug('expect before: {b}'.format(b=child.before))
                log.debug('expect after: {a}'.format(a=child.after))

                self._exit_session(child)
                if r == 0:
                    return
        raise ConsoleError("Did not get a login prompt from %s!" % self.name)

    def spawn_sol_log(self, dest_path):
        """
        Using the psutil module, spawn a conserver process and redirect its
        output to a file.

        :returns: a psutil.Popen object
        """
        console_cmd = self._console_command()
        pexpect_templ = \
            "import pexpect; " \
            "pexpect.run('{cmd}', logfile=file('{log}', 'w'), timeout=None)"
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
        proc = psutil.Popen(
            python_cmd,
            env=os.environ,
        )
        return proc

    def check_power(self, state, timeout=None):
        pass

    def check_status(self, timeout=None):
        pass

    def hard_reset(self):
        pass

    def power_cycle(self):
        pass

    def power_on(self):
        pass

    def power_off(self):
        pass

    def power_off_for_interval(self, interval=30):
        pass
