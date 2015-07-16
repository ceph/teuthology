from pytest import raises
from teuthology.config import FakeNamespace
from teuthology.exceptions import ConfigError
from teuthology.orchestra.cluster import Cluster
from teuthology.orchestra.remote import Remote
from teuthology.task.docker import Docker

from . import TestTask

import socket


class TestDockerTask(TestTask):
    klass = Docker
    task_name = 'docker'

    def setup(self):
        self.ctx = FakeNamespace()
        self.ctx.cluster = Cluster()
        self.ctx.cluster.add(Remote('host0'), ['mon.0', 'osd.0'])
        self.ctx.cluster.add(Remote('host1'), ['mon.1', 'osd.1'])
        self.ctx.cluster.add(Remote('host2'), ['mon.2', 'client.0'])
        self.ctx.config = {}
        self.task_config = {'command': ['start'], 'services': ''}

    def test_setup(self):
        # test with an empty config
        task_config = {}
        task = Docker(self.ctx, task_config)
        with raises(ConfigError) as excinfo:
            task.setup()
        assert excinfo.value.message.startswith("Expecting 'command'")

        # with empty command
        task_config = {'command': [], 'roles': ''}
        task = Docker(self.ctx, task_config)
        with raises(ConfigError) as excinfo:
            task.setup()
        assert excinfo.value.message.startswith("Expecting at least")

        # with incorrect command
        task_config = {'command': ['foo'], 'roles': ''}
        task = Docker(self.ctx, task_config)
        with raises(ConfigError) as excinfo:
            task.setup()
        assert excinfo.value.message.startswith("Unknown command")

        # missing roles or services
        task_config = {'command': ['start']}
        task = Docker(self.ctx, task_config)
        with raises(ConfigError) as excinfo:
            task.setup()
        assert excinfo.value.message.startswith("Expecting 'services'")

        # with correct values
        task_config = {'command': ['start'], 'roles': ''}
        task = Docker(self.ctx, task_config)
        task.setup()
        task_config = {'command': ['start', 'pull', 'stop'], 'services': ''}
        task = Docker(self.ctx, task_config)
        task.setup()

    def test_make_conf_with_services(self):
        task_config = {
            'services': {
                'foo': {
                    'image': 'bar/foo:latest',
                    'instances': {
                        'foo.1': {
                            'ship': 'host0'
                        }
                    }
                }
            }
        }
        task = Docker(self.ctx, task_config)
        task.generate_maestro_conf()

        c = task.maestro_config

        assert isinstance(c, dict)
        assert len(c.items()) != 0

        assert c['name'] == 'teuthology'
        assert c['docker_defaults']['port'] == 2375

        ships = c['ships']
        assert ships['host0']['ip'] == 'host0'
        assert ships['host1']['ip'] == 'host1'
        assert ships['host2']['ip'] == 'host2'

        assert c['services'] == task_config['services']

    def test_make_conf_with_roles_and_defaults(self):
        task_config = {'roles': {}}

        task = Docker(self.ctx, task_config)
        task.generate_maestro_conf()

        c = task.maestro_config

        assert isinstance(c, dict)
        assert len(c.items()) != 0

        assert c['name'] == 'teuthology'
        assert c['docker_defaults']['port'] == 2375

        ships = c['ships']
        assert ships['host0']['ip'] == 'host0'
        assert ships['host1']['ip'] == 'host1'
        assert ships['host2']['ip'] == 'host2'

        service = c['services']

        assert 'mon' in service
        assert 'image' in service['mon']
        assert 'net' in service['mon']
        assert 'env' in service['mon']
        assert 'instances' in service['mon']
        assert 'mon.0' in service['mon']['instances']
        assert 'mon.1' in service['mon']['instances']
        assert 'mon.2' in service['mon']['instances']
        assert 'ship' in service['mon']['instances']['mon.0']
        assert 'ship' in service['mon']['instances']['mon.1']
        assert 'ship' in service['mon']['instances']['mon.2']
        assert service['mon']['image'] == 'ceph/mon:latest'
        assert service['mon']['net'] == 'host'
        assert service['mon']['env']['MON_IP_AUTO_DETECT'] == 1
        assert service['mon']['instances']['mon.0']['ship'] == 'host0'
        assert service['mon']['instances']['mon.1']['ship'] == 'host1'
        assert service['mon']['instances']['mon.2']['ship'] == 'host2'

        assert 'osd' in service
        assert 'image' in service['osd']
        assert 'instances' in service['osd']
        assert 'osd.0' in service['osd']['instances']
        assert 'osd.1' in service['osd']['instances']
        assert 'ship' in service['osd']['instances']['osd.0']
        assert 'ship' in service['osd']['instances']['osd.1']
        assert service['osd']['image'] == 'ceph/osd:latest'
        assert service['osd']['instances']['osd.0']['ship'] == 'host0'
        assert service['osd']['instances']['osd.1']['ship'] == 'host1'

        assert 'client' in service
        assert 'image' in service['client']
        assert 'instances' in service['client']
        assert 'client.0' in service['client']['instances']
        assert 'ship' in service['client']['instances']['client.0']
        assert service['client']['image'] == 'ceph/client:latest'
        assert service['client']['instances']['client.0']['ship'] == 'host2'

    def test_make_conf_with_roles_and_no_defaults(self):
        task_config = {
            'port': 2345,
            'roles': {
                'tag': 'hammer',
                'registry_repo': 'foo'
            }
        }

        task = Docker(self.ctx, task_config)
        task.generate_maestro_conf()

        c = task.maestro_config

        assert isinstance(c, dict)
        assert len(c.items()) != 0

        assert c['docker_defaults']['port'] == 2345

        service = c['services']
        assert 'osd' in service
        assert service['osd']['image'] == 'foo/osd:hammer'

    def test_begin(self):
        if port_open('localhost', 2375):
            ctx = FakeNamespace()
            ctx.cluster = Cluster()
            ctx.cluster.add(Remote('localhost'), ['osd.0'])
            ctx.config = {}
            task_config = {
                'command': ['pull'],
                'roles': {
                }
            }
            task = Docker(ctx, task_config)
            task.begin()


def port_open(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex((host, port))
    if result == 0:
        return True
    else:
        return False
