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

class Rook(Task):
    name = 'Rook'
    __doc__ = """
    A task to deploy rook operator and also create ceph related
    resources like cluster, pool etc

    - Rook:
        version: 0.9
        git_url: <github.com>
        clone_path: <path/to/clone>

    This task depends on openshift-ansible task for creation of
    openshift cluster and to have ctx readily available with
    information like master node etc.
    """


    def __init__(self, ctx, config):
        super(Rook, self).__init__(ctx, config)
        config = config['vars']
        if 'git_url' in config:
            self.url = config['git_url']
        if 'branch' in config:
            self.branch = config['branch']
        if 'clone_path' in config:
            self.clone_path = config['clone_path']
        if 'go_path' in config:
            self.go_path = config['go_path']
        else:
            self.go_path = '/home/ubuntu/go'
        if 'rook_yamls' in config:
            self.rook_yamls = config['rook_yamls']
        self.create_cluster = False
        if 'create_cluster' in config:
            self.create_cluster = config['create_cluster']
        for (remote, roles) in self.cluster.only("masters").\
                    remotes.iteritems():
            self.master = remote
            break

    def install_go(self):
        for remote in self.ctx.cluster.remotes.iterkeys():
            remote.run(args=['sudo', 'sed', '-i', '-e',
                    run.Raw('"s/^enabled=0/enabled=1/"'),
                    run.Raw('/etc/yum.repos.d/epel.repo')])
        self.master.run(args=['sudo', 'yum', run.Raw('-y'), 'install',
                run.Raw('golang')])

    def clone_repo(self):
        self.master.run(args=['sudo', 'mkdir', run.Raw('-p'),
                            run.Raw(self.clone_path)])
        self.master.run(args=['sudo', 'chmod', run.Raw('-R'), '777',
                            run.Raw(self.clone_path)])
        self.master.run(args=['git', 'clone', run.Raw(self.url),
                run.Raw(self.clone_path), '--branch',
                run.Raw(self.branch)])

    def deploy_rook(self):
        self.master.run(args=['cd', run.Raw(self.clone_path), run.Raw(';'),
                'sudo', 'make', run.Raw('-j4'),
                run.Raw("IMAGES='ceph'"), 'build',
                run.Raw('GOPATH={}'.format(self.go_path))])

    def label_node(self, remote, label):
        '''given a remote, label it with label'''
        log.info("labeling {node} with {label}".format(
                node=remote.hostname, label=label))
        self.master.run(args=['oc', 'label', 'node', remote.hostname,
                    run.Raw(label)])
        proc = self.master.run(args=['oc', 'get', 'nodes',
                    run.Raw('--show-labels')])
        if proc.stdout:
            out = proc.stdout.getvalue()
            log.info(out)

    def oc_create(self, ypath):
        proc = self.master.run(args=['oc', 'create', '-f',
                    run.Raw(ypath)],
                    stdout=StringIO(),)
        if proc.stdout:
            out = proc.stdout.getvalue()
        if proc.stderr:
            out = proc.stderr.getvalue()
        log.info(out)

    def operator_prereq(self):
        ''' prereq before running rook operator'''
        label = ['node-role.kubernetes.io/compute=true']
        label.append('role=mon-node')
        for remote in self.ctx.cluster.remotes.iterkeys():
            for la in label:
                self.label_node(remote, la)
        '''using scc.yaml for security context'''
        self.oc_create(os.path.join(self.rook_yamls, "scc.yaml"))

    def patch_operator(self, op_yaml):
        local_path = self.master.get_file(op_yaml)
        with open(local_path, "r") as opyaml:
            data = opyaml.readlines()
        index = 0
        for line in data:
            if 'ROOK_HOSTPATH_REQUIRES_PRIVILEGED' in line:
                data[index+1] = data[index+1].replace('false', 'true')
                break
            index = index + 1
        misc.write_file(self.master, op_yaml, data)

    def rook_operator(self):
        self.operator_prereq()
        op_yaml = os.path.join(self.rook_yamls, "operator.yaml")
        if self.create_cluster:
            self.patch_operator(op_yaml)
            self.oc_create(op_yaml)
            self.oc_create(os.path.join(self.rook_yamls, "cluster.yaml"))

    def prepare_rook(self):
        self.install_go()
        self.clone_repo()

    def setup(self):
        super(Rook, self).setup()
        self.prepare_rook()

    def begin(self):
        super(Rook, self).begin()
        self.deploy_rook()
        self.rook_operator()

task = Rook
