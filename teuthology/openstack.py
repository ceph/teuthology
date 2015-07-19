import json
import logging
import os
import paramiko
import re
import socket
import subprocess
import tempfile
import teuthology

from .contextutil import safe_while
from .config import config as teuth_config
from teuthology import misc

log = logging.getLogger(__name__)

class OpenStack(object):

    def __init__(self):
        self.key_filename = None
        self.username = 'ubuntu'
        self.up_string = "UNKNOWN"
        self.teuthology_suite = 'teuthology-suite'

    def run(self, command):
        return misc.sh(command)

    @staticmethod
    def get_value(result, field):
        return filter(lambda v: v['Field'] == field, result)[0]['Value']

    def image_exists(self, image):
        found = self.run("openstack image list -f json --property name='" +
                         image + "'")
        return len(json.loads(found)) > 0

    def net_id(self, network):
        r = json.loads(self.run("openstack network show -f json " +
                                network))
        return self.get_value(r, 'id')

    def flavor(self, hint, select):
        """
        Return the smallest flavor that satisfies the desired size.
        """
        flavors_string = self.run("openstack flavor list -f json")
        flavors = json.loads(flavors_string)
        found = []
        for flavor in flavors:
            if select and not re.match(select, flavor['Name']):
                continue
            if (flavor['RAM'] >= hint['ram'] and
                    flavor['VCPUs'] >= hint['cpus'] and
                    flavor['Disk'] >= hint['disk']):
                found.append(flavor)
        if not found:
            raise Exception("openstack flavor list: " + flavors_string +
                            " does not contain a flavor in which" +
                            " the desired " + str(hint) + " can fit")

        def sort_flavor(a, b):
            return (a['VCPUs'] - b['VCPUs'] or
                    a['RAM'] - b['RAM'] or
                    a['Disk'] - b['Disk'])
        sorted_flavor = sorted(found, cmp=sort_flavor)
        log.info("sorted flavor = " + str(sorted_flavor))
        return sorted_flavor[0]['Name']

    def cloud_init_wait(self, name_or_ip):
        log.debug('cloud_init_wait')
        client_args = {
            'timeout': 10,
            'username': self.username,
        }
        if self.key_filename:
            log.debug("using key " + self.key_filename)
            client_args['key_filename'] = self.key_filename
        with safe_while(sleep=2, tries=200,
                        action="cloud_init_wait " + name_or_ip) as proceed:
            success = False
            all_done = ("tail /var/log/cloud-init.log ; " +
                        " test -f /tmp/init.out && tail /tmp/init.out ; " +
                        " grep '" + self.up_string + "' " +
                        "/var/log/cloud-init.log")
            while proceed():
                client = paramiko.SSHClient()
                try:
                    client.set_missing_host_key_policy(
                        paramiko.AutoAddPolicy())
                    client.connect(name_or_ip, **client_args)
                except paramiko.PasswordRequiredException as e:
                    client.close()
                    raise Exception(
                        "The private key requires a passphrase.\n"
                        "Create a new key with:"
                        "  openstack keypair create myself > myself.pem\n"
                        "  chmod 600 myself.pem\n"
                        "and call teuthology-openstack with the options\n"
                        " --key-name myself --key-filename myself.pem\n")
                except paramiko.AuthenticationException as e:
                    client.close()
                    log.debug('cloud_init_wait AuthenticationException ' + str(e))
                    continue
                except socket.timeout as e:
                    client.close()
                    log.debug('cloud_init_wait connect socket.timeout ' + str(e))
                    continue
                except socket.error as e:
                    client.close()
                    log.debug('cloud_init_wait connect socket.error ' + str(e))
                    continue
                except Exception as e:
                    client.close()
                    if 'Unknown server' in str(e):
                        continue
                    else:
                        log.exception('cloud_init_wait ' + name_or_ip)
                        raise e
                log.debug('cloud_init_wait ' + all_done)
                stdin, stdout, stderr = client.exec_command(all_done)
                stdout.channel.settimeout(5)
                try:
                    out = stdout.read()
                    log.debug('cloud_init_wait stdout ' + all_done + ' ' + out)
                except socket.timeout as e:
                    client.close()
                    log.debug('cloud_init_wait socket.timeout ' + all_done)
                    continue
                log.debug('cloud_init_wait stderr ' + all_done +
                          ' ' + stderr.read())
                if stdout.channel.recv_exit_status() == 0:
                    success = True
                client.close()
                if success:
                    break
            return success

    def exists(self, name_or_id):
        try:
            self.run("openstack server show -f json " + name_or_id)
        except subprocess.CalledProcessError as e:
            if ('No server with a name or ID' not in e.output and
                    'Instance could not be found' not in e.output):
                raise e
            return False
        return True

    def get_addresses(self, instance_id):
        with safe_while(sleep=2, tries=30,
                        action="get ip " + instance_id) as proceed:
            while proceed():
                instance = self.run("openstack server show -f json " +
                                    instance_id)
                addresses = self.get_value(json.loads(instance), 'addresses')
                found = re.match('.*\d+', addresses)
                if found:
                    return addresses

    def get_ip(self, instance_id, network):
        return re.findall(network + '=([\d.]+)',
                          self.get_addresses(instance_id))[0]

    def get_floating_ip(self, instance_id):
        return re.findall('([\d.]+)$',
                          self.get_addresses(instance_id))[0]

class TeuthologyOpenStack(OpenStack):

    def __init__(self, args, config, argv):
        super(TeuthologyOpenStack, self).__init__()
        self.argv = argv
        self.args = args
        self.config = config
        self.up_string = 'teuthology is up and running'
        self.user_data = 'openstack-user-data.txt'

    def main(self):
        self.setup_logs()
        misc.read_config(self.args)
        self.key_filename = self.args.key_filename
        self.verify_openstack()
        ip = self.setup()
        if self.args.suite:
            self.run_suite()
        log.info("""
web interface: http://{ip}:8081/
ssh access   : ssh {username}@{ip} # logs in /usr/share/nginx/html
        """.format(ip=ip,
                   username=self.username))
        if self.args.teardown:
            self.teardown()

    def run_suite(self):
        original_argv = self.argv[:]
        argv = []
        while len(original_argv) > 0:
            if original_argv[0] in ('--name',
                                    '--key-name',
                                    '--key-filename',
                                    '--simultaneous-jobs'):
                del original_argv[0:2]
            elif original_argv[0] in ('--teardown'):
                del original_argv[0]
            else:
                argv.append(original_argv.pop(0))
        argv.append('/home/ubuntu/teuthology/teuthology/test/integration/openstack.yaml')
        command = (
            "source ~/.bashrc_teuthology ; " + self.teuthology_suite + " " +
            " --machine-type openstack " +
            " ".join(map(lambda x: "'" + x + "'", argv))
        )
        print self.ssh(command)

    def setup(self):
        if not self.cluster_exists():
            self.create_security_group()
            self.create_cluster()
        return self.get_floating_ip(self.args.name)

    def setup_logs(self):
        loglevel = logging.INFO
        if self.args.verbose:
            loglevel = logging.DEBUG
        teuthology.log.setLevel(loglevel)

    def ssh(self, command):
        client_args = {
            'username': self.username,
        }
        if self.key_filename:
            log.debug("using key " + self.key_filename)
            client_args['key_filename'] = self.key_filename
        ip = self.get_floating_ip(self.args.name)
        log.debug("ssh " + self.username + "@" + str(ip) + " " + command)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy())
        client.connect(ip, **client_args)
        stdin, stdout, stderr = client.exec_command(command)
        stdout.channel.settimeout(300)
        out = ''
        try:
            out = stdout.read()
            log.debug('teardown stdout ' + command + ' ' + out)
        except Exception:
            log.exception('teardown ' + command + ' failed')
        err = stderr.read()
        log.debug('teardown stderr ' + command + ' ' + err)
        return out + ' ' + err

    def verify_openstack(self):
        try:
            misc.sh("openstack server list")
        except subprocess.CalledProcessError:
            log.exception("openstack server list")
            raise Exception("verify openrc.sh has been sourced")
        if 'OS_AUTH_URL' not in os.environ:
            raise Exception('no OS_AUTH_URL environment varialbe')
        providers = (('cloud.ovh.net', 'ovh'),
                     ('control.os1.phx2', 'redhat'),
                     ('entercloudsuite.com', 'entercloudsuite'))
        self.provider = None
        for (pattern, provider) in providers:
            if pattern in os.environ['OS_AUTH_URL']:
                self.provider = provider
                break
        if not self.provider:
            raise Exception('OS_AUTH_URL=' + os.environ['OS_AUTH_URL'],
                            ' does is not a known OpenStack provider ' +
                            str(providers))


    def image(self):
        if self.provider == 'ovh':
            return 'Ubuntu 14.04'
        elif self.provider == 'redhat':
            return 'ubuntu-server-14.04-x86_64'
        elif self.provider == 'entercloudsuite':
            return 'GNU/Linux Ubuntu Server 14.04 Trusty Tahr x64'

    def flavor(self):
        hint = {
            'disk': 10, # GB
            'ram': 1024, # MB
            'cpus': 1,
        }
        if self.args.simultaneous_jobs > 25:
            hint['ram'] = 30000 # MB
        elif self.args.simultaneous_jobs > 10:
            hint['ram'] = 7000 # MB
        elif self.args.simultaneous_jobs > 3:
            hint['ram'] = 4000 # MB

        select = None
        if self.provider == 'ovh':
            select = '^(vps|eg)-'
        return super(TeuthologyOpenStack, self).flavor(hint, select)

    def net(self):
        if self.provider == 'entercloudsuite':
            return "--nic net-id=default"
        else:
            return ""

    def get_user_data(self):
        path = tempfile.mktemp()
        template = open(self.user_data).read()
        openrc = ''
        for (var, value) in os.environ.iteritems():
            if var.startswith('OS_'):
                openrc += ' ' + var + '=' + value
        if self.args.integration_tests:
            run_tests = 'yes'
        else:
            run_tests = 'no'
        log.debug("OPENRC = " + openrc +
                  "RUN_TESTS = " + run_tests +
                  "NWORKERS = " + str(self.args.simultaneous_jobs) +
                  "PROVIDER = " + self.provider)
        content = (template.
                   replace('OPENRC', openrc).
                   replace('RUN_TESTS', run_tests).
                   replace('NWORKERS', str(self.args.simultaneous_jobs)).
                   replace('PROVIDER', self.provider))
        open(path, 'w').write(content)
        log.debug("get_user_data: " + content + " written to " + path)
        return path

    def create_security_group(self):
        try:
            misc.sh("openstack security group show teuthology")
            return
        except subprocess.CalledProcessError:
            pass
        # TODO(loic): this leaves the teuthology vm very exposed
        # it would be better to be very liberal for 192.168.0.0/16
        # and 172.16.0.0/12 and 10.0.0.0/8 and only allow 80/8081/22
        # for the rest.
        misc.sh("""
openstack security group create teuthology
openstack security group rule create --dst-port 1:10000 teuthology
#openstack security group rule create --dst-port 8081 teuthology # pulpito
#openstack security group rule create --dst-port 443 teuthology # https
#openstack security group rule create --dst-port 115 teuthology # sftp
#openstack security group rule create --dst-port 80 teuthology # http
#openstack security group rule create --dst-port 22 teuthology # ssh
openstack security group rule create --proto udp --dst-port 53 teuthology # dns
        """)

    def create_cluster(self):
        user_data = self.get_user_data()
        misc.sh("openstack server create " +
                " --image '" + self.image() + "' " +
                " --flavor '" + self.flavor() + "' " +
                " " + self.net() +
                " --key-name " + self.args.key_name +
                " --user-data " + user_data +
                " --security-group teuthology" +
                " --wait " + self.args.name)
        os.unlink(user_data)
        ip = self.get_floating_ip(self.args.name)
        return self.cloud_init_wait(ip)

    def cluster_exists(self):
        if not self.exists(self.args.name):
            return False
        ip = self.get_floating_ip(self.args.name)
        return self.cloud_init_wait(ip)

    def teardown(self):
        self.ssh("sudo /etc/init.d/teuthology stop || true")
        misc.sh("openstack server delete --wait " + self.args.name)

def main(ctx, argv):
    return TeuthologyOpenStack(ctx, teuth_config, argv).main()
