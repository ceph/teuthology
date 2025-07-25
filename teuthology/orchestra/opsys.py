import re

from packaging.version import parse as parse_version, Version


DISTRO_CODENAME_MAP = {
    "ubuntu": {
        "24.04": "noble",
        "22.04": "jammy",
        "20.04": "focal",
        "18.04": "bionic",
        "17.10": "artful",
        "17.04": "zesty",
        "16.10": "yakkety",
        "16.04": "xenial",
        "15.10": "wily",
        "15.04": "vivid",
        "14.10": "utopic",
        "14.04": "trusty",
        "13.10": "saucy",
        "12.04": "precise",
    },
    "debian": {
        "7": "wheezy",
        "8": "jessie",
        "9": "stretch",
        "10": "buster",
        "11": "bullseye",
        "12": "bookworm",
    },
    "rhel": {
        "9": "plow",
        "8": "ootpa",
        "7": "maipo",
        "6": "santiago",
    },
    "alma": {
        "8.10": "alma",
        "9.5": "alma",
    },
    "rocky": {
        "8.10": "rocky",
        "9.5": "rocky",
        "10.0": "rocky",
    },
    "centos": {
        "10": "stream",
        "9": "stream",
        "8": "core",
        "7": "core",
        "6": "core",
    },
    "fedora": {
        "28": "28",
        "27": "27",
        "26": "26",
        "25": "25",
        "24": "24",
        "23": "23",
        "22": "22",
        "21": "21",
        "20": "heisenbug",
    },
    "opensuse": {
        "1.0": "tumbleweed",
        "15.0": "leap",
        "15.1": "leap",
        "15.2": "leap",
        "15.3": "leap",
        "15.4": "leap",
        "15.5": "leap",
        "42.2": "leap",
        "42.3": "leap",
    },
    "sle": {
        "12.1": "sle",
        "12.2": "sle",
        "12.3": "sle",
        "15.0": "sle",
        "15.1": "sle",
        "15.2": "sle",
        "15.3": "sle",
        "15.4": "sle",
        "15.5": "sle",
    },
}

DEFAULT_OS_VERSION = dict(
    ubuntu="22.04",
    fedora="25",
    centos="9.stream",
    opensuse="15.4",
    sle="15.2",
    rhel="8.6",
    rocky="9.5",
    alma="9.5",
    debian='8.0'
)


class OS(object):
    """
    Class that parses either /etc/os-release or the output of 'lsb_release -a'
    and provides OS name and version information.

    Must be initialized with OS.from_lsb_release or OS.from_os_release
    """

    __slots__ = ['name', 'version', 'codename', 'package_type']

    _deb_distros = ('debian', 'ubuntu')
    _rpm_distros = ('fedora', 'rhel', 'centos', 'opensuse', 'sle')

    def __init__(self, name=None, version=None, codename=None):
        self.name = name
        self.version = version or self._codename_to_version(name, codename)
        self.codename = codename or self._version_to_codename(name, version)
        self._set_package_type()

    @staticmethod
    def _version_to_codename(name, version):
        for (_version, codename) in DISTRO_CODENAME_MAP[name].items():
            if str(version) == _version or str(version).split('.')[0] == _version:
                return codename

    @staticmethod
    def _codename_to_version(name, codename):
        for (version, _codename) in DISTRO_CODENAME_MAP[name].items():
            if codename == _codename:
                return version
        raise RuntimeError("No version found for %s %s !" % (
            name,
            codename,
        ))

    @classmethod
    def from_lsb_release(cls, lsb_release_str):
        """
        Parse output from lsb_release -a and populate attributes

        Given output like:
            Distributor ID: Ubuntu
            Description:    Ubuntu 12.04.4 LTS
            Release:        12.04
            Codename:       precise

        Attributes will be:
            name = 'ubuntu'
            version = '12.04'
            codename = 'precise'
        Additionally, we set the package type:
            package_type = 'deb'
        """
        str_ = lsb_release_str.strip()
        name = cls._get_value(str_, 'Distributor ID')
        if name == 'RedHatEnterpriseServer':
            name = 'rhel'
        elif name.startswith('openSUSE'):
            name = 'opensuse'
        elif name.startswith('SUSE'):
            name = 'sle'
        name = name.lower()

        version = cls._get_value(str_, 'Release')
        codename = cls._get_value(str_, 'Codename').lower()
        obj = cls(name=name, version=version, codename=codename)

        return obj

    @classmethod
    def from_os_release(cls, os_release_str):
        """
        Parse /etc/os-release and populate attributes

        Given output like:
            NAME="Ubuntu"
            VERSION="12.04.4 LTS, Precise Pangolin"
            ID=ubuntu
            ID_LIKE=debian
            PRETTY_NAME="Ubuntu precise (12.04.4 LTS)"
            VERSION_ID="12.04"

        Attributes will be:
            name = 'ubuntu'
            version = '12.04'
            codename = None
        Additionally, we set the package type:
            package_type = 'deb'
        """
        str_ = os_release_str.strip()
        version = cls._get_value(str_, 'VERSION_ID')
        name = cls._get_value(str_, 'ID').lower()
        if name == 'sles':
            name = 'sle'
        elif name == 'opensuse-leap':
            name = 'opensuse'
        elif name == 'opensuse-tumbleweed':
            name = 'opensuse'
        elif name == 'centos':
            if parse_version(version) >= Version("8.0"):
                version = f"{version}.stream"
        elif name == 'almalinux':
            name = 'alma'
        obj = cls(name=name, version=version)
        return obj


    @classmethod
    def version_codename(cls, name, version_or_codename):
        """
        Return (version, codename) based on one input, trying to infer
        which we're given
        """
        codename = None
        version = None

        try:
            codename = OS._version_to_codename(name, version_or_codename)
        except KeyError:
            pass

        try:
            version = OS._codename_to_version(name, version_or_codename)
        except (KeyError, RuntimeError):
            pass

        if version:
            codename = version_or_codename
        elif codename:
            version = version_or_codename
        else:
            raise KeyError('%s not a %s version or codename' %
                           (version_or_codename, name))
        return version, codename


    @staticmethod
    def _get_value(str_, name):
        regex = '^%s[:=](.+)' % name
        match = re.search(regex, str_, flags=re.M)
        if match:
            return match.groups()[0].strip(' \t"\'')
        return ''

    def _set_package_type(self):
        if self.name in self._deb_distros:
            self.package_type = "deb"
        elif self.name in self._rpm_distros:
            self.package_type = "rpm"

    def to_dict(self):
        return dict(
            name=self.name,
            version=self.version,
            codename=self.codename,
        )

    def __str__(self):
        return " ".join([self.name, self.version]).strip()

    def __repr__(self):
        return "OS(name={name}, version={version}, codename={codename})"\
            .format(name=repr(self.name),
                    version=repr(self.version),
                    codename=repr(self.codename))

    def __eq__(self, other):
        if self.name.lower() != other.name.lower():
            return False
        normalize = lambda s: s.lower().removesuffix(".stream")
        return normalize(self.version) == normalize(other.version)
