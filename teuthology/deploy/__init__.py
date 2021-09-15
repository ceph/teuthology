import docopt
import json
import logging
import openstack
import os
import shutil
import sys
import time
import yaml

from pathlib import Path

from teuthology.orchestra.remote import Remote
from teuthology.repo_utils import fetch_repo
from teuthology.misc import sh

default_deployment_type = 'openstack'
#default_os_image='openSUSE-Leap-15.2-JeOS.x86_64-15.2-OpenStack-Cloud-Build31.415'
default_os_image='openSUSE-Leap-15.3-JeOS.x86_64-15.3-OpenStack-Cloud-Build9.122'

if 'opensuse' in default_os_image.lower():
    default_username = 'opensuse'
else:
    default_username = 'root'


doc = """
usage: teuthology-deploy --help
       teuthology-deploy [-v] [options]

Deploy teuthology to a given host.


Options:

  -h, --help                        Show this help message and exit
  -v, --verbose                     Show more detailed info
  -d, --debug                       Show debug info

Command options:
  --clean                           Cleanup deployment.
  --list                            List available deployments.
  --ssh                             Login to the deployment node..

  -K, --clean-on-error              Cleanup deployment if an error occurred.
  -n, --name <name>                 Deployment name [default: {default_name}]
  -N, --name-server                 Setup name server and nsupdate_web.
  --domain <domain>                 Target nodes domain name
  -C, --teuthology-config <path>    Use teuthology-config on deployment node
  -L, --libcloud-config <path>      Extra teuthology yaml file
  --libcloud-ssl-cert <path>        Path to libcloud ssl cert file, for example:
                                    /usr/share/pki/trust/anchors/SUSE_Trust_Root.crt.pem
  --dispatcher <jobs>               Deploy dispatcher with given job limit.
  --workers <num>                   Deploy given number of workers.
  --targets <num>                   Add targets to the platform.


  -u, --username <login>            Remote server login name [default: {default_username}]
  -i, --identity-file <path>        Remote server access ssh secret file
                                    [default: {default_identity_file}]

  -D, --deployment-type <type>      Use following backend: openstack, libvirt, ssh
                                    [default: openstack]

  --ceph-cm-ansible <path>          Path to ceph-cm-ansible repo clone
                                    [default: {ceph_cm_ansible}]
Deployment Options:

  --teuthology-repo <url>           Teuthology repo URL [default: {teuthology_repo}]
  --pulpito-repo <url>              Pulpito repo URL
  --paddles-repo <url>              Paddles repo URL
  --ceph-repo <url>                 Ceph repo URL

OpenStack Options:

  --os-cloud <cloud>         Deploy teuthology to the given cloud
                             [default: {default_os_cloud}]
  --os-image <image>         Override openstack image for deployment
                             [default: {default_os_image}]
  --os-flavor <flavor>       Override openstack flavor for deployment, for example:
                             s1-8, b2-7 [default: b2-7]
  --os-floating <floating>   Use floating network for deployment
  --os-network <network>     Use network for deployment node
  --os-keypair <keypair>     Use keyname for booting node [default: {default_os_keypair}]
  --os-userdata <path>       Use custom userdata for node creation

Host Options:

  -H, --host <addr>          Deployment host name or ip with ssh access.


Examples:

1. Build teuthology in openstack, setup named and nsupdate_web, start 8 workers and
   register 50 openstack clients in paddles.

  teuthology-deploy -N --workers 8 --targets 50

2. Build teuthology in openstack cloud 'de' with 'teuth-featured' name from another
   teuthology fork repository.

  teuthology-deploy -N --os-cloud de --name featured --teuthology-repo https://github.com/fork/teuthology

""".format(
    default_name=os.environ.get('USER'),
    default_os_cloud=os.environ.get('OS_CLOUD'),
    default_os_image=default_os_image,
    default_os_keypair=os.environ.get('USER'),
    default_username=default_username,
    default_identity_file=os.environ.get('HOME') + '/.ssh/id_rsa',
    ceph_cm_ansible='git+https://github.com/ceph/ceph-cm-ansible@master',
    teuthology_repo='https://github.com/ceph/teuthology',
)


from urllib.parse import urlparse

class Repo:
    ref = None
    url = None
    def __init__(self, uri: str, default_ref: str):
        if uri.startswith('git+'):
            _uri = uri[4:]
        else:
            _uri = uri
        u = urlparse(_uri)
        _path = u.path
        if '@' in _path:
            self.ref = _path.rsplit('@', 1)[1]
            l = len(self.ref) + 1
            self.url = _uri[:-l]
        else:
            self.url = _uri
            self.ref = default_ref

    def fetch(self):
        p = fetch_repo(self.url, self.ref)
        return Path(p)

def main():
    args = docopt.docopt(doc, sys.argv[1:])


    root_logger = logging.getLogger()
    handlers = root_logger.handlers
    for h in handlers:
        root_logger.removeHandler(h)

    if args.get('--verbose') or args.get('--debug'):
        #logging.root.setLevel(logging.DEBUG)
        logging.basicConfig(level=logging.DEBUG,
                datefmt='%Y-%m-%d %H:%M:%S',
                format='%(asctime)s %(levelname)s:%(message)s')
        logging.debug('Verbose mode is enabled')
    else:
        _info = logging.Formatter('%(message)s')
        _default = logging.Formatter('%(levelname)s:%(message)s')
        class InfoFormatter(logging.Formatter):
            def format(self, record):
                if record.levelno == logging.INFO:
                    return _info.format(record)
                else:
                    return _default.format(record)
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(InfoFormatter())
        logging.root.addHandler(h)
        logging.root.setLevel(logging.INFO)

    if args.get('--list'):
        Deployment.list_deployments()
        return

    deployment = Deployment.getDeployment(args)
    logging.debug(f'Using deployment type: {deployment.deployment}')

    if args.get('--clean'):
        logging.info(f'Cleaning deployment: {deployment.deployment_name}')
        deployment.load()
        deployment.clean()
    elif args.get('--ssh'):
        deployment.load()
        logging.debug(deployment.access_str())
        os.system(deployment.access_str())
    else:
        deployment.deploy()

class Deployment:
    home = os.environ.get('HOME') + '/.teuthology/deploy'
    deployment = None
    status = None
    nameserver = None
    dispatcher = None
    workers = None
    targets = None
    domain = None
    teuthology_repo = 'https://github.com/ceph/teuthology'
    _ceph_cm_ansible_path = None
    _libcloud_path = None

    def __init__(self, args):
        self.with_args(args)

    def with_args(self, args):
        self.args = args
        self.deployment_name = args.get('--name')
        self.username = args.get('--username')
        self.identity_file = args.get('--identity-file')
        self.deployment = args.get('--deployment-type')
        self.dispatcher = args.get('--dispatcher')
        self.workers = args.get('--workers')
        self.targets = args.get('--targets')
        self.nameserver = args.get('--name-server')
        self.domain = args.get('--domain')
        self.teuthology_repo = args.get('--teuthology-repo')
        self.paddles_repo = args.get('--paddles-repo')
        self.pulpito_repo = args.get('--pulpito-repo')
        self.ceph_cm_ansible = args.get('--ceph-cm-ansible')
        self.libcloud_ssl_cert = args.get('--libcloud-ssl-cert')
        libcloud_config = args.get('--libcloud-config')
        if libcloud_config:
            self._libcloud_path = Path(libcloud_config).absolute()

        logging.debug(f"Init deployment with name '{self.deployment_name}'")

    def getDeployment(args):
        d = args.get('--deployment-type')
        if d == 'openstack':
            return OpenStackDeployment(args)
        elif d == 'libvirt':
            logging.error('LibVirt deployment is not implemented yet')
            exit(1)
        elif d == 'ssh' or d == 'direct':
            logging.error('Direct ssh deployment is not implemented yet')
            exit(1)
        else:
            logging.error(
                f'Unsupported deployment type: {d}, try one of: openstack, libvirt, direct')
            exit(1)

    def list_deployments():
        logging.debug(f'Checking directory: {Deployment.home}')
        deployments = [_ for _ in os.listdir(Deployment.home)]
        if deployments:
            logging.info('Found deployments:')
            for name in deployments:
                logging.info(f'- {name}')

    @property
    def home_path(self):
        return Path(Deployment.home).joinpath(self.deployment_name)

    @property
    def meta_path(self):
        return self.home_path.joinpath('meta.json')

    @property
    def secrets_path(self):
        return self.home_path.joinpath('secrets')

    @staticmethod
    def branch_from_repo(repo, default_branch):
        """todo: rework"""
        repo_and_branch = repo.rsplit('@', 1)
        if len(repo_and_branch) > 2:
            return repo_and_branch[1]
        else:
            return default_branch

    @property
    def ansible_playbook_path(self):
        if self.nameserver:
            name = 'teuthology-suse-ns.yml'
        else:
            name = 'teuthology-suse.yml'
        return Path(__file__).absolute().parent.joinpath('ansible', name)

    @property
    def ceph_cm_ansible_path(self):
        if self._ceph_cm_ansible_path:
            return self._ceph_cm_ansible_path
        path = Path(self.ceph_cm_ansible)
        if path.exists():
            self._ceph_cm_ansible_path = path
        else:
            repo = Repo(self.ceph_cm_ansible, 'master')
            self._ceph_cm_ansible_path = repo.fetch()
        return self._ceph_cm_ansible_path

    @property
    def ansible_roles(self):
        return Path(__file__).absolute().parent.joinpath('ansible/roles')

    @property
    def teuthology_git_ref(self):
        return self.branch_from_repo(self.teuthology_repo, 'master')

    def prepare_secrets(self):
        if not self.secrets_path.exists():
            self.secrets_path.mkdir(parents=True)
        paddles_data = dict(
            ansible_ssh_user='root',
            db_pass='poijpoij',
        )
        with open(self.secrets_path.joinpath('paddles.yml'), 'w') as f:
            yaml.dump(paddles_data, f)

    @property
    def libcloud_yaml_path(self):
        if self._libcloud_path:
            return self._libcloud_path
        path = Path(__file__).absolute().parent.joinpath('libcloud/ovh.cfg.orig')
        if path.exists():
            return path
        else:
            raise Exception(f'No file found by "{path}"')

    def get_meta(self):
        meta = dict(
            status=self.status,
            deployment=self.deployment,
            dispatcher=self.dispatcher,
            workers=self.workers,
            targets=self.targets,
        )
        return meta

    def set_meta(self, meta):
        self.status = meta.get('status')
        self.deployment = meta.get('deployment')
        self.dispatcher = meta.get('dispatcher')
        self.workers = meta.get('workers')
        self.targets = meta.get('targets')

    def deploy(self):
        pass

    def clean(self):
        pass

    def load(self):
        logging.debug(f'Loading meta from {self.meta_path}')
        with open(self.meta_path) as f:
            meta = json.load(f)
            self.set_meta(meta)

    def delete_home(self):
        if self.home_path.exists():
            shutil.rmtree(self.home_path)

    def save(self):
        if not self.home_path.exists():
            self.home_path.mkdir(parents=True)
        with open(self.meta_path, 'w') as f:
            json.dump(self.get_meta(), f)

    def access_str(self, user: str = None) -> str:
        pass


class OpenStackDeployment(Deployment):
    server_id = None
    access_address = None
    floating_address_id = None
    def __init__(self, args):
        super().__init__(args)
        self.cloud = args.get('--os-cloud')
        self.deployment_node = f'teuth-{self.deployment_name}'

        assert(self.cloud)


    def get_meta(self):
        meta = super().get_meta()
        meta['cloud'] = self.cloud
        meta['server_id'] = self.server_id
        meta['access_address'] = self.access_address
        meta['floating_address_id'] = self.floating_address_id
        return meta

    def set_meta(self, meta):
        super().set_meta(meta)
        self.cloud = meta.get('cloud')
        self.server_id = meta.get('server_id')
        self.access_address = meta.get('access_address')
        self.floating_address_id = meta.get('floating_address_id')

    def get_connect(self):
        debug = self.args.get('--debug')
        if debug:
            openstack.enable_logging(debug=True)
        else:
            openstack.enable_logging(debug=False)
            logging.getLogger("paramiko").setLevel(logging.WARNING)
        conn = openstack.connect(self.cloud)
        return conn


    def access_host(self):
        return f'{self.username}@{self.access_address}'

    def access_str(self, user: str = None) -> str:
        ssh_user = user or self.username
        return f'ssh -i {self.identity_file} {ssh_user}@{self.access_address}'

    def deploy(self):
        self.conn = self.get_connect()
        try:
            self.create_server()
            logging.debug(f'Connecting to {self.access_host()} using identity {self.identity_file}')
            r = Remote(self.access_host(),
                                                        host_key=self.identity_file)
            r.reconnect(timeout=3*60, sleep_time=10)
            logging.debug('get uptime')
            uptime = r.sh('uptime')
            logging.debug(uptime)
            logging.info(
                f'Server is created and can be accessed using: {self.access_str()}')
            self.save()
            # grep ^TEUTHOLOGYBOOT /var/log/cloud-init-output.log
            count = 0
            while True:
                if r.sh('grep ^TEUTHOLOGYBOOT /var/log/cloud-init-output.log',
                                                                check_status=False):
                    break
                if count > 8:
                    raise Exception('userdata script is not complete')
                count += 1
                time.sleep(60)

            # prepare deployment
            self.prepare(r)
            logging.info(f'Server is ready, login with {self.access_str()}')
        except Exception as e:
            logging.debug(f'Caught exception: {e}')
            if self.args.get('--clean-on-error'):
                self.clean()
            raise e

    @property
    def teuthology_server_yaml_path(self):
        return self.home_path.joinpath('teuthology_server.yml')

    def prepare(self, remote):
        # make teuthology server yaml
        self.prepare_secrets()
        teuthology_server = dict(
            teuthology_name=self.deployment_name,
            teuthology_addr=self.private_address,
            nameserver_addr=self.private_address,
            machine_type=self.cloud,
            secrets_path=str(self.secrets_path),
            log_host=self.access_address,
            dispatcher=int(self.dispatcher or 0),
            workers=int(self.workers or 0),
            targets=int(self.targets or 0),
            yaml_extra_path=str(self.libcloud_yaml_path),
            ansible_ssh_user=self.username,
            ansible_ssh_common_args='-o StrictHostKeyChecking=no'
        )
        if self.teuthology_git_ref:
            teuthology_server.update(
                teuthology_git_ref=self.teuthology_git_ref
            )
        if self.nameserver:
            zone_domain = self.domain or f'{self.cloud}.local'
            teuthology_server.update(
                nsupdate_web_server=self.private_address,
                lab_domain=zone_domain,
                zone_name=zone_domain,
                zone_domain=zone_domain,
            )
        else:
            zone_domain = self.domain or 'local'
            teuthology_server.update(
                lab_domain=zone_domain,
                zone_name=zone_domain,
                zone_domain=zone_domain,
            )

        teuthology_server_yaml_path = self.home_path.joinpath('teuthology_server.yml')
        with open(teuthology_server_yaml_path, 'w') as f:
            yaml.dump(teuthology_server, f)

        ceph_cm_ansible_roles = self.ceph_cm_ansible_path.joinpath('roles')
        ansible_config = (
            '[defaults]\n'
            '#stdout_callback = unixy\n'
            'stdout_callback = yaml\n'
            f'roles_path={ceph_cm_ansible_roles}:{self.ansible_roles}\n'
            '\n'
            '[ssh_connection]\n'
            'pipelining = True\n'
        )

        ansible_config_path = self.home_path.joinpath('teuthology-ansible.cfg')
        with open(ansible_config_path, 'w') as f:
            f.write(ansible_config)

        ansible_inventory = (
            '[nameserver]\n'
            f'{self.access_address}\n'
            '[teuthology]\n'
            f'{self.access_address}\n'
            '[paddles]\n'
            f'{self.access_address}\n'
            '[pulpito]\n'
            f'{self.access_address}\n'
        )
        ansible_inventory_path = self.home_path.joinpath('teuthology-inventory')
        with open(ansible_inventory_path, 'w') as f:
            f.write(ansible_inventory)

        teuthology_role_config_yaml = dict(
            author="{{ lookup('env', 'USER') }}",
            #ceph_repo: https://github.com/ceph/ceph.git
            teuthology_branch="{{ teuthology_git_ref | default('master') }}",
            )
        if self.libcloud_ssl_cert:
            teuthology_role_config_yaml.update(
                libcloud_ssl_cert_file=self.libcloud_ssl_cert,
            )
        if self.teuthology_repo:
            repo = Repo(self.teuthology_repo, 'master')
            teuthology_role_config_yaml.update(
                teuthology_repo=repo.url,
                teuthology_branch=repo.ref,
            )

        if self.paddles_repo:
            repo = Repo(self.paddles_repo, 'master')
            teuthology_role_config_yaml.update(
                paddles_repo=repo.url,
                paddles_branch=repo.ref,
            )

        if self.pulpito_repo:
            repo = Repo(self.pulpito_repo, 'master')
            teuthology_role_config_yaml.update(
                pulpito_repo=repo.url,
                pulpito_branch=repo.ref,
            )

        teuthology_config_yaml_path = self.home_path.joinpath('teuthology-role.cfg.yaml')
        with open(teuthology_config_yaml_path, 'w') as f:
            yaml.dump(teuthology_role_config_yaml, f)

        teuthology_defaults_path = Path(__file__).absolute().parent.joinpath('ansible/teuthology-defaults.yml')
        teuthology_vars_path = Path(__file__).absolute().parent.joinpath('ansible/teuthology-vars.yml')
        ansible_playbook_command = (
            f'ANSIBLE_CONFIG={ansible_config_path} ansible-playbook -vvv --key-file {self.identity_file}'
            f' --user {self.username}'
            f' -i {ansible_inventory_path}'
            f' -e @{self.teuthology_server_yaml_path}'
            f' -e @{teuthology_defaults_path}'
            f' -e @{teuthology_config_yaml_path}'
            f' -e @{teuthology_vars_path}'
            f' {self.ansible_playbook_path}'
        )
        logging.info(f'=== will run next command ===\n{ansible_playbook_command}')

        # run ansible
        sh(ansible_playbook_command)

    def clean(self):
        self.conn = self.get_connect()
        self.delete_server()
        self.delete_home()

    def create_server(self):
        c = self.conn.compute
        present_servers = c.servers()
        server_names = [_.name for _ in present_servers]
        logging.info('Found servers: ' + ', '.join(server_names))
        if self.deployment_node in server_names:
            logging.error(f'Deployment server {self.deployment_node} already exists')
            exit(1)
        image_name = self.args.get('--os-image')
        if not image_name:
            raise Exception('Image name is undefined, use --os-image option')
        image = self.conn.get_image(image_name)
        if not image:
            raise Exception(f'Image "{image_name}" was not found')
        logging.info(f'Found image with id: {image.id}')
        flavor_name = self.args.get('--os-flavor')
        flavor = self.conn.get_flavor(flavor_name)
        if not flavor:
            raise Exception(f'Flavor "{flavor_name}" was not found')
        logging.info(f'Found flavor with id: {flavor.id}')
        keypair_name = self.args.get('--os-keypair')
        keypair = self.conn.compute.find_keypair(keypair_name)
        if not keypair:
            raise Exception(f'Keypair "{keypair_name}" was not found')
        logging.info(f'Found keypair with id: {keypair.id}')

        userdata_file = self.args.get('--os-userdata')
        if userdata_file:
            userdata_path = Path(userdata_file)
        else:
            userdata_path = Path(__file__).absolute().parent.joinpath('openstack/userdata-ovh.yaml.orig')
        userdata = userdata_path.read_text()

        params = dict(
            name=self.deployment_node,
            image=image.id,
            flavor=flavor.id,
            key_name=keypair.name,
            userdata=userdata,
        )

        floating = self.args.get('--os-floating')
        network = self.args.get('--os-network')
        if network:
            params['network'] = network

        logging.info(f'Creating server with name: {self.deployment_node}')
        server = self.conn.create_server(**params)
        server_id = server.id

        if server_id:
            self.server_id = server_id

        self.save()

        logging.info(f'Created server with id: {server_id}')
 
        wait_seconds = 10
        timeout = 8 * 60 # seconds
        server_status = None
        start_time = time.time()
        while server_status != 'ACTIVE':
            time.sleep(wait_seconds)
            server = self.conn.compute.get_server(server_id)
            server_status = server.status
            if server_status == 'ERROR':
                x = self.conn.get_server_by_id(server_id)
                if 'fault' in server and 'message' in server['fault']:
                    raise Exception('Server creation failed with message: '
                                   f"{x['fault']['message']}")
                else:
                    raise Exception('Unknown failure while creating server: {x}')
                
            if timeout > (time.time() - start_time):
                logging.info(f'Server {server.name} is not active. '
                             f'Waiting {wait_seconds} seconds...')

        for i, v in server.addresses.items():
            logging.debug(f'Server network "{i}": {v}')

        ipv4=[x['addr'] for i, nets in server.addresses.items()
            for x in nets if x['version'] == 4][0]
        self.private_address = ipv4
        logging.info(f'Got IPv4 address for server: {ipv4}')
        if floating:
            faddr = self.conn.create_floating_ip(
                    network=floating,
                    server=server,
                    fixed_address=ipv4,
                    wait=True,
                    )
            ipv4 = faddr['floating_ip_address']
            self.floating_address_id = faddr['id']
        self.access_address = ipv4
        logging.info(f'Server can be accessed using address {ipv4}')

        self.save()

    def delete_server(self):
        try:
            s = self.conn.compute.get_server(self.server_id)
            logging.debug(f'Delete server "{s.name}" with id {s.id}')
            self.conn.compute.delete_server(s.id)
        except Exception as e:
            logging.warning(e)
        if self.floating_address_id:
            self.conn.delete_floating_ip(self.floating_address_id)

