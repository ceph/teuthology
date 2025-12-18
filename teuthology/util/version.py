import re
from functools import total_ordering
from typing import Union, List


@total_ordering
class LooseVersion:
    """
    A flexible version comparison class that handles arbitrary version strings.
    Compares numeric components numerically and alphabetic components lexically.
    """

    _component_re = re.compile(r'(\d+|[a-z]+|\.)', re.IGNORECASE)

    def __init__(self, vstring: str):
        self.vstring = str(vstring)
        self.version = self._parse(self.vstring)

    def _parse(self, vstring: str) -> List[Union[int, str]]:
        """Parse version string into comparable components."""
        components = []
        for match in self._component_re.finditer(vstring.lower()):
            component = match.group()
            if component != '.':
                # Try to convert to int, fall back to string
                try:
                    components.append(int(component))
                except ValueError:
                    components.append(component)
        return components

    def __str__(self) -> str:
        return self.vstring

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}('{self.vstring}')"

    def __eq__(self, other) -> bool:
        if not isinstance(other, LooseVersion):
            other = LooseVersion(str(other))
        return self.version == other.version

    def __lt__(self, other) -> bool:
        if not isinstance(other, LooseVersion):
            other = LooseVersion(str(other))
        return self.version < other.version

    def __hash__(self) -> int:
        return hash(tuple(self.version))
