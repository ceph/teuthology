from typing import Optional, Iterator, Callable

class Role(object):
    """
    Role is label used for cluster nodes to allocate different services and
    apply correspondingly distinct operations. It is represented by a string
    which can have up to three point separated components.
    1) role
    2) role.index
    3) cluster.role.index
    where:
    role is a string value
    index is an integer value
    cluster is a string label or name of cluster where the role is allocated/
    """
    DEFAULT_CLUSTER_NAME = 'ceph'

    def __init__(self, role):
        cluster, name, index = self.as_tuple(role)
        self.name = name
        self.index = index
        self.cluster = cluster

    @property
    def short(self) -> str:
        return f"{self.name}.{self.index}"

    @staticmethod
    def as_tuple(role: str):
        """
        Return a tuple of cluster, role name, and role index.

        If no cluster is included in the role, the default cluster, 'ceph', is used
        """
        cluster = Role.DEFAULT_CLUSTER_NAME
        if role.count('.') > 1:
            cluster, role = role.split('.', 1)
        name, index = role.split('.', 1)
        return cluster, name, index

    @staticmethod
    def make_matcher(name:str, cluster: Optional[str] = None) -> Callable[[str], bool]:
        """
        Returns a matcher function for whether role is of given name.

        :param cluster: cluster name to check in matcher (ignore by default)
        """
        def _matcher(role:str):
            """
            Return type based on the starting role name.

            If there is more than one period, strip the first part
            (ostensibly a cluster name) and check the remainder for the prefix.
            """
            cluster_name, role_name, _ = Role.as_tuple(role)
            if cluster is not None and cluster_name != cluster:
                return False
            return role_name == name
        return _matcher


    @staticmethod
    def iter_name_index(roles: list[str], name: str, cluster: Optional[str] = None) -> Iterator[tuple[str,str]]:
        """
        Generator of (name, index) pairs.

        Each call returns the next possible role with the name specified.
        :param roles: list of roles possible
        :param name: name of role
        """
        for role in Role.iter_roles(roles, name, cluster):
            _, n, i = Role.as_tuple(role)
            yield (n, i)
 

    @staticmethod
    def iter_roles(roles: list[str], name: str, cluster: Optional[str] = None) -> Iterator[str]:
        """
        Generator of roles.

        Each call returns the next possible role with name specified.

        :param roles_for_host: list of roles possible
        :param name:  role name
        :param cluster: cluster name
        """
        match_role = Role.make_matcher(name, cluster)
        for role in roles:
            if not match_role(role):
                continue
            yield role

