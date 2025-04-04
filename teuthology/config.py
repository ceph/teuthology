import os
import yaml
import logging
try:
    from collections.abc import MutableMapping
except ImportError:
    from collections import MutableMapping


# Configuration constants
SYSTEM_CONFIG_PATH = '/etc/teuthology.yaml'
USER_CONFIG_PATH = '~/.teuthology.yaml'
CONFIG_PATH_VAR_NAME = 'TEUTHOLOGY_CONFIG'  # name of env var to check


def init_logging():
    log = logging.getLogger(__name__)
    return log

log = init_logging()


class YamlConfig(MutableMapping):
    """
    A configuration object populated by parsing a yaml file, with optional
    default values.

    Note that modifying the _defaults attribute of an instance can potentially
    yield confusing results; if you need to do modify defaults, use the class
    variable or create a subclass.
    """
    _defaults = dict()

    def __init__(self, yaml_path=None):
        self.yaml_path = yaml_path
        if self.yaml_path:
            self.load()
        else:
            self._conf = dict()

    def load(self, conf=None):
        if conf is not None:
            if isinstance(conf, dict):
                self._conf = conf
                return
            elif conf:
                self._conf = yaml.safe_load(conf)
                return
        if os.path.exists(self.yaml_path):
            with open(self.yaml_path) as f:
                self._conf = yaml.safe_load(f)
        else:
            log.debug("%s not found", self.yaml_path)
            self._conf = dict()

    def update(self, in_dict):
        """
        Update an existing configuration using dict.update()

        :param in_dict: The dict to use to update
        """
        self._conf.update(in_dict)

    @classmethod
    def from_dict(cls, in_dict):
        """
        Build a config object from a dict.

        :param in_dict: The dict to use
        :returns:       The config object
        """
        conf_obj = cls()
        conf_obj._conf = in_dict
        return conf_obj

    def to_dict(self):
        """
        :returns: A shallow copy of the configuration as a dict
        """
        return dict(self._conf)

    @classmethod
    def from_str(cls, in_str):
        """
        Build a config object from a string or yaml stream.

        :param in_str: The stream or string
        :returns:      The config object
        """
        conf_obj = cls()
        conf_obj._conf = yaml.safe_load(in_str)
        return conf_obj

    def to_str(self):
        """
        :returns: str(self)
        """
        return str(self)

    def get(self, key, default=None):
        return self._conf.get(key, default)

    def __str__(self):
        return yaml.safe_dump(self._conf, default_flow_style=False).strip()

    def __repr__(self):
        return self.__str__()

    def __getitem__(self, name):
        return self.__getattr__(name)

    def __getattr__(self, name):
        return self._conf.get(name, self._defaults.get(name))

    def __contains__(self, name):
        return self._conf.__contains__(name)

    def __setattr__(self, name, value):
        if name.endswith('_conf') or name in ('yaml_path'):
            object.__setattr__(self, name, value)
        else:
            self._conf[name] = value

    def __delattr__(self, name):
        del self._conf[name]

    def __len__(self):
        return self._conf.__len__()

    def __iter__(self):
        return self._conf.__iter__()

    def __setitem__(self, name, value):
        self._conf.__setitem__(name, value)

    def __delitem__(self, name):
        self._conf.__delitem__(name)


class TeuthologyConfig(YamlConfig):
    """
    This class is intended to unify teuthology's many configuration files and
    objects. Currently it serves as a convenient interface to
    ~/.teuthology.yaml or equivalent.
    """
    yaml_path = USER_CONFIG_PATH  # yaml_path is updated in _get_config_path
    _defaults = {
        'archive_base': '/home/teuthworker/archive',
        'archive_upload': None,
        'archive_upload_key': None,
        'archive_upload_url': None,
        'automated_scheduling': False,
        'reserve_machines': 5,
        'ceph_git_base_url': 'https://github.com/ceph/',
        'ceph_git_url': None,
        'ceph_qa_suite_git_url': None,
        'ceph_cm_ansible_git_url': None,
        'use_conserver': False,
        'conserver_master': 'conserver.front.sepia.ceph.com',
        'conserver_port': 3109,
        'gitbuilder_host': 'gitbuilder.ceph.com',
        'githelper_base_url': 'http://githelper.ceph.com',
        'check_package_signatures': True,
        'job_threshold': 500,
        'lab_domain': 'front.sepia.ceph.com',
        'lock_server': 'http://paddles.front.sepia.ceph.com/',
        'max_job_age': 1209600,  # 2 weeks
        'max_job_time': 259200,  # 3 days
        'nsupdate_url': 'http://nsupdate.front.sepia.ceph.com/update',
        'results_server': 'http://paddles.front.sepia.ceph.com/',
        'results_ui_server': 'http://pulpito.ceph.com/',
        'results_sending_email': 'teuthology',
        'results_timeout': 43200,
        'src_base_path': os.path.expanduser('~/src'),
        'verify_host_keys': True,
        'watchdog_interval': 120,
        'fog_reimage_timeout': 1800,
        'fog_wait_for_ssh_timeout': 600,
        'kojihub_url': 'http://koji.fedoraproject.org/kojihub',
        'kojiroot_url': 'http://kojipkgs.fedoraproject.org/packages',
        'koji_task_url': 'https://kojipkgs.fedoraproject.org/work/',
        'baseurl_template': 'http://{host}/{proj}-{pkg_type}-{dist}-{arch}-{flavor}/{uri}',
        'use_shaman': True,
        'shaman_host': 'shaman.ceph.com',
        'teuthology_path': None,
        'suite_verify_ceph_hash': True,
        'suite_allow_missing_packages': False,
        'openstack': {
            'clone': 'git clone http://github.com/ceph/teuthology',
            'user-data': 'teuthology/openstack/openstack-{os_type}-{os_version}-user-data.txt',
            'ip': '1.1.1.1',
            'machine': {
                'disk': 20,
                'ram': 8000,
                'cpus': 1,
            },
            'volumes': {
                'count': 0,
                'size': 1,
            },
        },
        'rocketchat': None,
        'sleep_before_teardown': 0,
        'ssh_key': None,
        'active_machine_types': [],
    }

    def __init__(self, yaml_path=None):
        super(TeuthologyConfig, self).__init__(yaml_path or self.yaml_path)

    def get_ceph_cm_ansible_git_url(self):
        return (self.ceph_cm_ansible_git_url or
                self.ceph_git_base_url + 'ceph-cm-ansible.git')

    def get_ceph_qa_suite_git_url(self):
        return (self.ceph_qa_suite_git_url or
                self.get_ceph_git_url())

    def get_ceph_git_url(self):
        return (self.ceph_git_url or
                self.ceph_git_base_url + 'ceph-ci.git')


class JobConfig(YamlConfig):
    pass


class FakeNamespace(YamlConfig):
    """
    This class is meant to behave like a argparse Namespace

    We'll use this as a stop-gap as we refactor commands but allow the tasks
    to still be passed a single namespace object for the time being.
    """
    def __init__(self, config_dict=None):
        if not config_dict:
            config_dict = dict()
        self._conf = self._clean_config(config_dict)
        set_config_attr(self)

    def _clean_config(self, config_dict):
        """
        Makes sure that the keys of config_dict are able to be used.  For
        example the "--" prefix of a docopt dict isn't valid and won't populate
        correctly.
        """
        result = dict()
        for key, value in config_dict.items():
            new_key = key
            if new_key.startswith("--"):
                new_key = new_key[2:]
            elif new_key.startswith("<") and new_key.endswith(">"):
                new_key = new_key[1:-1]

            if "-" in new_key:
                new_key = new_key.replace("-", "_")

            result[new_key] = value

        return result

    def __getattr__(self, name):
        """
        We need to modify this for FakeNamespace so that getattr() will
        work correctly on a FakeNamespace instance.
        """
        if name in self._conf:
            return self._conf[name]
        elif name in self._defaults:
            return self._defaults[name]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name == 'teuthology_config':
            object.__setattr__(self, name, value)
        else:
            super(FakeNamespace, self).__setattr__(name, value)

    def __repr__(self):
        return repr(self._conf)

    def __str__(self):
        return str(self._conf)


def set_config_attr(obj):
    """
    Set obj.teuthology_config, mimicking the old behavior of misc.read_config
    """
    obj.teuthology_config = config


def _get_config_path():
    """Look for a teuthology config yaml and return it's path.
    Raises ValueError if no config yaml can be found.
    """
    paths = [
        os.path.join(os.path.expanduser(USER_CONFIG_PATH)),
        SYSTEM_CONFIG_PATH,
    ]
    if CONFIG_PATH_VAR_NAME in os.environ:
        paths.insert(0, os.path.expanduser(os.environ[CONFIG_PATH_VAR_NAME]))
    for path in paths:
        if os.path.exists(path):
            return path
    log.warning(f"no teuthology config found, looked for: {paths}")
    return None


config = TeuthologyConfig(yaml_path=_get_config_path())
