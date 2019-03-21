import json
import os
import re
import logging
import yaml
import time
import errno
import socket
from cStringIO import StringIO

from . import Task
from tempfile import NamedTemporaryFile
from ..config import config as teuth_config
from ..misc import get_scratch_devices
from teuthology import contextutil
from teuthology.orchestra import run
from teuthology.orchestra.daemon import DaemonGroup
from teuthology.task.install import ship_utilities
from teuthology import misc
from teuthology import misc as teuthology
from teuthology.parallel import parallel
from teuthology.exceptions import CommandFailedError
from teuthology import repo_utils

log = logging.getLogger(__name__)

groups_to_roles = dict(
    masters='masters',
    etcd='etcd',
    nodes='nodes'
)


class OpenshiftAnsible(Task):
    name = 'openshift_ansible'

    __doc__ = """
    A task to setup openshift cluster using openshift-ansible

    - openshift-ansible:
	ansible-version: 2.7
	docker: 1.13
	vars:
	  docker_dev: /dev/sdc #disk used for docker storage
	  docker_vg: 'docker-vg'
    """

    def __init__(self, ctx, config):
	super(OpenshiftAnsible, self).__init__(ctx, config)
	config = self.config or dict()
	self.playbook = None
	if 'playbook' in config:
	    self.playbook = self.config['playbook']

	if 'vars' not in config:
	    self.vars = dict()
	    config['vars'] = vars
	self.vars = config['vars']
	self.inventory = None
	self.installer = None
	#TODO read the following from config yaml
	self.OSEv3_children = groups_to_roles
	self.OSEv3_vars={'ansible_ssh_user':'ubuntu',
		    'ansible_become':'true',
		    'install_method':'rpm',
		    'os_update':'false',
		    'oreg_url':'registry.access.redhat.com/openshift3/ose-${component}:v3.11',
		    'install_update_docker':'true',
		    'docker_storage_driver':'devicemapper',
		    'openshift_deployment_type':'openshift-enterprise',
		    'openshift_release':'v3.11',
		    'openshift_docker_insecure_registries':'registry.access.redhat.com',
		    'openshift_web_console_install':'false',
		    'openshift_enable_service_catalog':'false',
		    'debug_level':'5',
		    'openshift_disable_check':'docker_image_availability,memory_availability',
		    'openshift_check_min_host_disk_gb':'2',
		    'openshift_check_min_host_memory_gb':'1',
		    'openshift_portal_net':'172.31.0.0/16',
		    'openshift_master_cluster_method':'native',
		    'openshift_clock_enabled':'true',
		    'openshift_use_openshift_sdn':'true',
		    'openshift_cluster_monitoring_operator_install':'false',
		    'openshift_hosted_registry_selector':'\"node-role.kubernetes.io/infra=true\"'}
	self.ansible_hosts=None

    def generate_hosts_file(self):
	"""
	#generate openshift-ansible hosts file
	#sample file looks like following
	#
	# It should live in /etc/ansible/hosts
	#
	#   - Comments begin with the '#' character
	#   - Blank lines are ignored
	#   - Groups of hosts are delimited by [header] elements
	#   - You can enter hostnames or ip addresses
	#   - A hostname/ip can be a member of multiple groups

	# Ex 1: Ungrouped hosts, specify before any group headers.

	## green.example.com
	## blue.example.com
	## 192.168.100.1
	## 192.168.100.10

	# Ex 2: A collection of hosts belonging to the 'webservers' group

	## [webservers]
	## alpha.example.org
	## beta.example.org
	## 192.168.1.100
	## 192.168.1.110

	# If you have multiple hosts following a pattern you can specify
	# them like this:

	## www[001:006].example.com

	# Ex 3: A collection of database servers in the 'dbservers' group

	## [dbservers]
	##
	## db01.intranet.mydomain.net
	## db02.intranet.mydomain.net
	## 10.25.1.56
	## 10.25.1.57

	# Here's another example of host ranges, this time there are no
	# leading 0s:

	## db-[99:101]-node.example.com
	[OSEv3:children]
	masters
	nodes
	etcd
	#
	## # Set variables common for all OSEv3 hosts
	[OSEv3:vars]
	ansible_ssh_user=root
	##openshift_deployment_type=openshift-enterprise
	install_method=rpm
	os_update=false
	oreg_url=registry.access.redhat.com/openshift3/ose-${component}:v3.11
	install_update_docker=true
	docker_storage_driver=devicemapper
	ansible_ssh_user=root
	openshift_deployment_type=openshift-enterprise
	openshift_release=v3.11
	##openshift_cockpit_deployer_prefix=registry.access.redhat.com/openshift3/
	openshift_docker_insecure_registries=registry.access.redhat.com
	openshift_web_console_install=true
	openshift_enable_service_catalog=false
	###osm_use_cockpit=false
	###osm_cockpit_plugins=['cockpit-kubernetes']
	###openshift_node_kubelet_args={'pods-per-core': ['10'],
		'max-pods': ['250'], 'image-gc-high-threshold': ['90'],
		'image-gc-low-threshold': ['80']}
	###openshift_hosted_registry_selector="role=node,registry=enabled"
	###openshift_hosted_router_selector="role=node,router=enabled"
	debug_level=5
	#openshift_set_hostname=true
	#openshift_override_hostname_check=true
	openshift_disable_check=docker_image_availability,memory_availability
	openshift_check_min_host_disk_gb=2
	openshift_check_min_host_memory_gb=1
	openshift_portal_net=172.31.0.0/16
	openshift_master_cluster_method=native
	openshift_clock_enabled=true
	openshift_use_openshift_sdn=true
	openshift_cluster_monitoring_operator_install=false
	##
	##openshift_master_cluster_hostname=<master node>
	##openshift_master_cluster_public_hostname=<master node>
	##
	##  # registry
	##  # openshift_hosted_registry_storage_kind=ceph        <--Enabling this fails the installation
	##  # openshift_hosted_registry_storage_volume_size=10Gi <--Enabling this fails the installation
	openshift_hosted_registry_selector="node-role.kubernetes.io/infra=true"
	##
	##
	##
	## # host group for masters
	[masters]
	example.com
	##
	## # host group for etcd
	[etcd]
	example005.example.com
	example009.example.com
	example015.example.com
	#
	## etcd2.example.com
	## etcd3.example.com
	##
	## # host group for nodes, includes region info
	[nodes]
	example005.example.com openshift_node_group_name='node-config-master'
	example009.example.com openshift_node_group_name='node-config-compute'
	example015.example.com openshift_node_group_name='node-config-compute'
	"""
	hosts_dict = dict()
        for group in sorted(groups_to_roles.keys()):
            role_prefix = groups_to_roles[group]
            log.info("role_prefix:{} ".format(role_prefix))

            def want(role): return role.startswith(role_prefix)

            for (remote, roles) in self.cluster.only(
                    role_prefix).remotes.iteritems():
		log.info("Current node is {}".format(remote.hostname))
		log.info("roles are {}".format(roles))
		if "masters" in roles and not self.installer:
		    log.info("current role prefix {}".format(role_prefix))
		    log.info("Host is {}".format(remote.hostname))
		    self.installer = remote
		    self.master = remote
                hostname = remote.hostname
              	#  host_vars = self.get_host_vars(remote)
		host_vars = None
                if group not in hosts_dict:
                    hosts_dict[group] = {hostname: host_vars}
                elif hostname not in hosts_dict[group]:
                    hosts_dict[group][hostname] = host_vars

        hosts_stringio = StringIO()
	hosts_stringio.write('[OSEv3:vars]\n')
	for k, v in self.OSEv3_vars.iteritems():
	    hosts_stringio.write('%s=%s\n' %(k, v))
	hosts_stringio.write('[OSEv3:children]\n')
	for k, v in self.OSEv3_children.iteritems():
	    hosts_stringio.write('%s\n' %v)

	grp_master = False

        for group in sorted(hosts_dict.keys()):
            hosts_stringio.write('[%s]\n' % group)
            for hostname in sorted(hosts_dict[group].keys()):
		if group == "nodes" :
		    if not grp_master:
			suffix = "openshift_node_group_name='node-config-master-infra'".format()
			host_line = "{host} {suf}".format(
				    host=hostname,
				    suf=suffix)
			grp_master = True
		    else:
			suffix = "openshift_node_group_name='node-config-compute'".format()
			host_line = "{host} {suf}".format(
				    host=hostname,
				    suf=suffix)
		else:
		    host_line = hostname
                hosts_stringio.write('%s\n' % host_line)
            hosts_stringio.write('\n')
       # hosts_stringio.seek(0)
       # self.inventory = self._write_hosts_file(
       #     prefix='openshift_ansible_hosts_',
       #     content=hosts_stringio.read().strip())
	self.data = hosts_stringio.getvalue()

    def install_pkgs(self, remote, pkgs):
	plist=" ".join(pkg for pkg in pkgs)
	remote.run(args=['sudo', 'sed', '-i', '-e',
			run.Raw('"s/^enabled=0/enabled=1/"'),
			run.Raw('/etc/yum.repos.d/epel.repo')])
	remote.run(args=['sudo', 'yum', '-y', 'install',
			run.Raw(plist)])
	docker_config = "/etc/sysconfig/docker-storage-setup"
	if 'docker_dev' in self.vars:
	    disk = self.vars['docker_dev']

	if 'docker_vg' in self.vars:
	    vg = self.vars['docker_vg']
	storage_setup = "DEVS={disk}\nVG={vg}\n".format(\
			disk=disk, vg=vg)
	teuthology.sudo_write_file(remote, docker_config, storage_setup)
	remote.run(args=['sudo', 'docker-storage-setup'])
	time.sleep(5)
	retry = True

	while retry:
	    try:
		remote.run(args=['sudo', 'systemctl', 'enable', 'docker'])
		retry = False
	    except:
		pass

	time.sleep(5)
	remote.run(args=['sudo', 'systemctl', 'start', 'docker'])

    def package_prep(self):
	'''
	Just for time being this will install packages and this should be
	offloaded to other task.
	'''
	#util_pkg = ['wget','git','net-tools','bind-utils','iptables-services',
	#	'bridge-utils','kexec-tools','sos','psacct']
	util_pkg=[]
	oc_pkg = ['docker-1.13.1', 'ansible']
	pkgs = oc_pkg + util_pkg

	with parallel() as p:
	    for remote in self.ctx.cluster.remotes.iterkeys():
		log.info("Installing pkgs on node: %s", remote.shortname)
		p.spawn(self.install_pkgs, remote, pkgs)

    def docker_pull(self, remote, registry):
	for img in registry:
	    remote.run(args = ['sudo', 'docker', 'pull',
			run.Raw('registry.access.redhat.com/'+img)])

    def install_ansible(self):
	default = "/usr/share/ansible/openshift-ansible/"
	if 'git_url' in self.vars:
	    url = self.vars['git_url']
	    branch = self.vars['git_branch']
	    clone_path = self.vars['git_clonepath']
	    self.installer.run(args=['sudo','mkdir',
					run.Raw(clone_path)])
	    self.installer.run(args=['sudo', 'chmod', '-R', '777',
					run.Raw(clone_path)])
	    self.installer.run(args = ['git', 'clone',
				run.Raw(url), run.Raw(clone_path),
				'--branch', run.Raw('release-3.11')])
	    return clone_path
	else:
	    self.installer.run(args = ['sudo', 'yum', run.Raw('-y'), 'install',
					run.Raw('openshift-ansible')])
	    return default

    def execute_playbook(self):
	'''
	Execute openshift ansible-playbook
	'''
	oc_path = self.install_ansible()
	self.oc_path = oc_path
	prereq_playbook = "playbooks/prerequisites.yml"
	oc_playbook = "playbooks/deploy_cluster.yml"
	teuthology.sudo_write_file(self.installer, "/etc/ansible/hosts", self.data)
	log.info("Installer node is :{}".format(self.installer.hostname))
	self.installer.run(args = ['ansible-playbook',run.Raw('-u'),
				'ubuntu', run.Raw(os.path.join(oc_path, prereq_playbook))])
	log.info(type(self.installer))

	registry = ['openshift3/ose-node:v3.11',
		    'openshift3/ose-haproxy-router:v3.11',
		    'openshift3/ose-deployer:v3.11',
		    'openshift3/ose-control-plane:v3.11',
		    'openshift3/ose-web-console:v3.11',
		    'openshift3/ose-docker-registry:v3.11',
		    'openshift3/ose-pod:v3.11',
		    'openshift3/oauth-proxy:v3.11',
		    'openshift3/registry-console:v3.11',
		    'rhel7/etcd:3.2.22'
	]

	with parallel() as p:
	    for remote in self.ctx.cluster.remotes.iterkeys():
		log.info("Pulling docker images")
		p.spawn(self.docker_pull, remote, registry)

	self.installer.run(args = ['ansible-playbook','-u','ubuntu',
				run.Raw(os.path.join(oc_path, oc_playbook)),
				'-e', 'openshift_disable_check=docker_storage'])

    def setup_stage_cdn(self, ctx, config):
	"""
	Configure internal stage cdn
	"""
	with parallel() as p:
	    for remote in ctx.cluster.remotes.iterkeys():
		if remote.os.name == 'rhel':
		    log.info("subscribing stage cdn on : %s", remote.shortname)
		    p.spawn(self._subscribe_stage_cdn, remote, teuth_config)

    def _subscribe_stage_cdn(self, remote, teuth_config):
	cdn_user = self.config['cdn_user']
	pool_id = self.config['pool_id']
	self._unsubscribe_stage_cdn(remote)
	cdn_config = teuth_config.get('cdn-config', dict())
	server_url = cdn_config.get('server-url', 'subscription.rhsm.stage.redhat.com:443/subscription')
	base_url = cdn_config.get('base-url', 'https://cdn.stage.redhat.com')
	username = cdn_config.get('username', cdn_user)
	password = cdn_config.get('password')
	remote.run(
	    args=[
		'sudo', 'subscription-manager', '--force', 'register',
		run.Raw('--serverurl=' + server_url),
		run.Raw('--baseurl=' + base_url),
		run.Raw('--username=' + username),
		run.Raw('--password=' + password),
		],
	    timeout=720)
	remote.run(
	    args=[
		'sudo', 'subscription-manager','attach', '--pool={}'.format(pool_id),
	    ],
	    timeout=720)
	self._enable_rhel_repos(remote)


    def _unsubscribe_stage_cdn(self, remote):
	try:
	    remote.run(args=['sudo', 'subscription-manager', 'unregister'],
		       check_status=False)
	except CommandFailedError:
	    # FIX ME
	    log.info("unregistring subscription-manager failed, ignoring")

    def _enable_rhel_repos(self, remote):
	rhel_7_rpms = ['rhel-7-server-rpms',
		       'rhel-7-server-optional-rpms',
		       'rhel-7-server-extras-rpms',
		       'rhel-7-server-ansible-2.6-rpms',
		       'rhel-7-fast-datapath-rpms',
		       'rhel-7-server-ose-3.11-rpms']
	for repo in rhel_7_rpms:
	    remote.run(args=['sudo', 'subscription-manager',
			     'repos', '--enable={r}'.format(r=repo)])



    def setup(self):
	super(OpenshiftAnsible, self).setup()
	self.setup_stage_cdn(self.ctx, self.ctx.config)
	self.package_prep()
	self.generate_hosts_file()

    def begin(self):
	super(OpenshiftAnsible, self).begin()
	self.execute_playbook()
	proc = self.master.run(args=['sudo', 'oc', 'get', 'pods',
			    run.Raw('--all-namespaces')])
	if proc.stdout:
	    out = proc.stdout.getvalue()
	log.info(out)

    def teardown(self):
	with parallel() as p:
	    for remote in self.ctx.cluster.remotes.iterkeys():
		p.spawn(self._unsubscribe_stage_cdn, remote)
	self.installer.run(args=['ansible-playbook', os.path.join(self.oc_path,\
				"playbooks/adhoc/uninstall.yml")])


task = OpenshiftAnsible
