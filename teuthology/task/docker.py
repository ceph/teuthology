from . import Task

from teuthology.exceptions import ConfigError

from maestro.__main__ import create_parser
from maestro.maestro import Conductor
import shlex


class Docker(Task):
    """
    A task to execute maestro-ng commands. The main assumption is that every
    host provided in "targets" is running a docker daemon.

    Required configuration parameters:
        command:    Required; List of commands. Any of "pull", "stop"
                    or "start". Commands are separated by space and are executed
                    in the given list-order.
        services:   The service(s) that are being operated on. This has the same
                    format as `maestro-ng`'s for describing services. The only
                    thing to notice is that the value of the `ship` option
                    (where a service runs) has to take values that come from one
                    of the hosts specified in teuthology's `targets` option.
        roles:      Create services from roles specified in teuthology's config.
                    These should correspond to the roles specified in
                    teuthology's `roles` option. An optional `tag` config
                    specifies the corresponding image's version to execute
                    (defaults to `latest`). Also, a registry other than 'ceph'
                    (the default) can be specified with the `registry_repo`
                    option.
    Optional configuration parameters:
        port:       TCP port where the docker daemon is listening (defaults to
                    '2375'). This should be enabled on every node.

    Examples:

    tasks:
    - docker:
        command: ["start"]
        services:
          paddles:
            image: ceph/paddles:latest
            paddles.0:
              ship: host1
              ports: { front: 8081 }
          pulpito:
            image: ceph/pulpito:latest
            requires: [ paddles ]
            pulpito.0:
              ship: host1
              ports: { front: 8080 }
          teuthology:
            image: ceph/teuthology:latest
            requires: [ pulpito ]
            teuthology.0:
              ship: host2
              ports: { queue: 11300 }
              env:
                LAB_DOMAIN: example.com
                LOCK_SERVER: http://pulpito.example.com:8080
                RESULTS_SERVER: http://pulpito.example.com:8080
                QUEUE_HOST: localhost
                QUEUE_PORT: 11300
                RESULTS_EMAIL: you@example.com
                ARCHIVE_BASE: /teuthworker/archive

    tasks:
    - docker:
        command: ["stop"]
        roles:
        port: 4653

    tasks:
    - docker:
        command: ["stop", "start"]
        roles:
          tag: hammer
          registry_repo: otherthanceph
    """

    def __init__(self, ctx, config):
        super(Docker, self).__init__(ctx, config)

    def setup(self):
        """"
        Validates the given config
        """
        if 'command' not in self.config:
            raise ConfigError("Expecting 'command' in task configuration")
        if 'services' not in self.config and 'roles' not in self.config:
            raise ConfigError("Expecting 'services' or 'roles' (or both)")

        if len(self.config['command']) == 0:
            raise ConfigError("Expecting at least 1 command")
        for c in self.config['command']:
            if (c != "start" and c != "pull" and c != "stop"):
                raise ConfigError("Unknown command '" + c + "'")

    def begin(self):
        """"
        Invokes maestro-ng with the given commands and arguments.
        """
        self.generate_maestro_conf()

        for cmd in self.config['command']:
            try:
                opts = create_parser().parse_args(shlex.split(cmd))
                c = Conductor(self.maestro_config)
                opts.things = [s.name for s in c.services.values()]
                getattr(c, opts.command)(**vars(opts))
            except:
                raise

    def generate_maestro_conf(self):
        """
        Obtain config to pass to maestro. For example, given the following
        teuthology configuration:

        ```yaml

        roles:
        -  [mon.0, mds.0, osd.0]
        -  [mon.1, osd.1]
        -  [mon.2, client.0]

        tasks:
        - docker:
            command: ["start"]
            services:
              foo:
                image: foo:latest
                instances:
                  foo1:
                    ship: host1
            roles:
              tag: hammer
        - radosbench:
            clients: [client.0]
            time: 360
        - interactive:

        targets:
          ubuntu@host1: ssh-rsa host1_key
          ubuntu@host2: ssh-rsa host2_key
          ubuntu@host3: ssh-rsa host3_key
        ```

        The generated maestro configuration is:

        ```yaml

        name: teuthology

        docker_defaults:
          port: 2375

        ships:
          host1: { ip: <host1> }
          host2: { ip: <host2> }
          host3: { ip: <host3> }

        services:
          foo:
            image: foo:latest
            instances:
              foo1:
                ship: host1
          mon:
            image: ceph/mon:hammer
            net: host
            env:
               MON_IP_AUTO_DETECT: 1
            instances:
              mon.0:
                ship: host1
              mon.1:
                ship: host2
              mon.2:
                ship: host3
          osd:
            image: ceph/osd:hammer
            requires: [ mon ]
            instances:
              osd.0:
                ship: host1
              osd.1:
                ship: host2
          mds:
            image: ceph/mds:hammer
            requires: [ osd ]
            instances:
              mds.0:
                ship: host1
          client:
            image: ceph/client:hammer
            requires: [ osd ]
            instances:
              client.0:
                ship: host3
        ```
        """

        self.maestro_config = {}
        self.maestro_config['name'] = 'teuthology'
        self.maestro_config['docker_defaults'] = {
            'port': self.config['port'] if 'port' in self.config else 2375
        }

        # ships
        self.maestro_config['ships'] = {}

        remotes = sorted(
            self.ctx.cluster.remotes.iterkeys(), key=lambda rem: rem.name)
        for remote in remotes:
            self.maestro_config['ships'].update({
                remote.name: {
                    'ip': remote.name
                }
            })

        # services
        self.maestro_config['services'] = {}

        if 'services' in self.config:
            self.maestro_config['services'].update(self.config['services'])

        if 'roles' in self.config:
            from_roles = get_services_for_roles(self.ctx, self.config['roles'])
            self.maestro_config['services'].update(from_roles)


def get_services_for_roles(ctx, config):
    services = {}

    repo = config['registry_repo'] if 'registry_repo' in config else 'ceph'
    tag = config['tag'] if 'tag' in config else 'latest'

    for role_category in ['mon', 'osd', 'mds', 'client']:
        services[role_category] = {
            'image': repo + '/' + role_category + ':' + tag,
        }

        services[role_category]['instances'] = {}

        if role_category is 'mon':
            services[role_category].update({
                'net': 'host',
                'env': {
                    'MON_IP_AUTO_DETECT': 1
                }
            })

        if role_category is 'osd':
            services[role_category].update({'requires': ['mon']})

        if role_category is 'mds' or role_category is 'client':
            services[role_category].update({'requires': ['osd']})

        for remote in ctx.cluster.remotes:
            for role in ctx.cluster.remotes[remote]:
                if role.startswith(role_category):
                    services[role_category]['instances'][role] = {
                        'ship': remote.name
                    }

    return services
