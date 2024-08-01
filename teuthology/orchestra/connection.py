"""
Connection utilities
"""
import paramiko
import os
import logging

from teuthology.config import config
from teuthology.contextutil import safe_while
from paramiko.hostkeys import HostKeyEntry
import sshtunnel

log = logging.getLogger(__name__)


def split_user(user_at_host):
    """
    break apart user@host fields into user and host.
    """
    try:
        user, host = user_at_host.rsplit('@', 1)
    except ValueError:
        user, host = None, user_at_host
    assert user != '', \
        "Bad input to split_user: {user_at_host!r}".format(user_at_host=user_at_host)
    return user, host


def create_key(keytype, key):
    """
    Create an ssh-rsa, ssh-dss or ssh-ed25519 key.
    """
    l = "{hostname} {keytype} {key}".format(hostname="x", keytype=keytype, key=key)

    ke = HostKeyEntry.from_line(l)
    assert ke, f'invalid host key "{keytype} {key}"'
    return ke.key


def connect(user_at_host, host_key=None, keep_alive=False, timeout=60,
            _SSHClient=None, _create_key=None, retry=True, key_filename=None):
    """
    ssh connection routine.

    :param user_at_host: user@host
    :param host_key: ssh key
    :param keep_alive: keep_alive indicator
    :param timeout:    timeout in seconds
    :param _SSHClient: client, default is paramiko ssh client
    :param _create_key: routine to create a key (defaults to local reate_key)
    :param retry:       Whether or not to retry failed connection attempts
                        (eventually giving up if none succeed). Default is True
    :param key_filename:  Optionally override which private key to use.

    :return: ssh connection.

    The connection is going to be established via tunnel if corresponding options
    are provided in teuthology configuration file. For example:

    tunnel:
      - hosts: ['hostname1.domain', 'hostname2.domain']
        bastion:
          host: ssh_host_name
          user: ssh_user_name
          port: 22
          identity: ~/.ssh/id_ed25519

    """
    user, host = split_user(user_at_host)
    if _SSHClient is None:
        _SSHClient = paramiko.SSHClient
    ssh = _SSHClient()

    if _create_key is None:
        _create_key = create_key

    if host_key is None:
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if config.verify_host_keys is True:
            ssh.load_system_host_keys()

    else:
        keytype, key = host_key.split(' ', 1)
        ssh.get_host_keys().add(
            hostname=host,
            keytype=keytype,
            key=_create_key(keytype, key)
            )

    connect_args = dict(
        hostname=host,
        username=user,
        timeout=timeout
    )

    if config.tunnel:
        for tunnel in config.tunnel:
            if host in tunnel.get('hosts'):
                bastion = tunnel.get('bastion')
                if not bastion:
                    log.error("The 'tunnel' config must include 'bastion' entry")
                    continue
                bastion_host = bastion.get('host')
                server = sshtunnel.SSHTunnelForwarder(
                    bastion_host,
                    ssh_username=bastion.get('user', None),
                    ssh_password=bastion.get('word', None),
                    ssh_pkey=bastion.get('identity'),
                    remote_bind_address=(host, 22))
                log.info(f'Starting tunnel to {bastion_host} for host {host}')
                server.start()
                local_port = server.local_bind_port
                log.debug(f"Local port for host {host} is {local_port}")
                connect_args['hostname'] = '127.0.0.1'
                connect_args['port'] = local_port
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                break

    key_filename = key_filename or config.ssh_key
    ssh_config_path = config.ssh_config_path or "~/.ssh/config"
    ssh_config_path = os.path.expanduser(ssh_config_path)
    if os.path.exists(ssh_config_path):
        ssh_config = paramiko.SSHConfig()
        ssh_config.parse(open(ssh_config_path))
        opts = ssh_config.lookup(host)
        if not key_filename and 'identityfile' in opts:
            key_filename = opts['identityfile']
        if 'hostname' in opts:
            connect_args['hostname'] = opts['hostname']
        if 'user' in opts:
            connect_args['username'] = opts['user']

    if key_filename:
        if not isinstance(key_filename, list):
            key_filename = [key_filename]
        key_filename = [os.path.expanduser(f) for f in key_filename]
        connect_args['key_filename'] = key_filename

    log.debug(connect_args)

    if not retry:
        ssh.connect(**connect_args)
    else:
        with safe_while(sleep=1, increment=3, action='connect to ' + host) as proceed:
            while proceed():
                auth_err_msg = f"Error authenticating with {host}"
                try:
                    ssh.connect(**connect_args)
                    break
                except EOFError:
                    log.error(f"{auth_err_msg}: EOFError")
                except paramiko.AuthenticationException as e:
                    log.error(f"{auth_err_msg}: {repr(e)}")
                except paramiko.SSHException as e:
                    auth_err_msg = f"{auth_err_msg}: {repr(e)}"
                    if not key_filename:
                        auth_err_msg = f"{auth_err_msg} (No SSH private key found!)"
                    log.exception(auth_err_msg)
    ssh.get_transport().set_keepalive(keep_alive)
    return ssh
