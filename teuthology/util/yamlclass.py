"""
Load YAML documents into dataclasses, reporting every problem with its
``file:line`` location.

Supported field types are ``str``, ``int``, ``bool``, ``list[T]``,
``T | None`` and nested dataclasses. Per-field behaviour is configured with
``dataclasses.field(metadata=...)``:

``aliases``
    Alternative key names accepted for the field.
``coerce``
    Called with the raw value before type checking; returns the value to use.
    May raise ``ValueError`` to report a problem.
``check``
    Called with the type-checked value; returns an error message, or None.
``doc``
    Human-readable description of the field.

Classes may also define:

``yaml_forbidden: ClassVar[Mapping[str, str]]``
    Keys that are rejected with a specific message instead of the generic
    "unknown key" one.
``yaml_validate(self, ctx: Context)``
    Called after the instance is built, for checks that involve several
    fields. Report problems with ``ctx.error()``.

Keys are matched after replacing ``-`` with ``_``.
"""
import dataclasses
import difflib
import types
import typing

from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

import yaml

T = TypeVar("T")

_MISSING = object()


@dataclass(frozen=True)
class FieldError:
    path: str
    line: int | None
    message: str

    def format(self, filename: str | None = None) -> str:
        location = filename or "<string>"
        if self.line is not None:
            location = f"{location}:{self.line}"
        if self.path:
            return f"{location}: {self.path}: {self.message}"
        return f"{location}: {self.message}"


class ValidationError(Exception):
    def __init__(self, errors: list[FieldError], filename: str | None = None):
        self.errors = sorted(
            errors, key=lambda e: (e.line is None, e.line or 0, e.path))
        self.filename = filename
        super().__init__(str(self))

    def __str__(self) -> str:
        return "\n".join(e.format(self.filename) for e in self.errors)


class LocatedDict(dict):
    """A dict that remembers where it and its keys/values were in the YAML."""
    line: int | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.key_lines: dict[Any, int] = {}
        self.value_lines: dict[Any, int] = {}


class LocatedList(list):
    """A list that remembers where it and its items were in the YAML."""
    line: int | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.item_lines: list[int] = []


def _line(node: yaml.Node) -> int:
    return node.start_mark.line + 1


class LocatingLoader(yaml.SafeLoader):
    """
    A SafeLoader that builds LocatedDict/LocatedList containers and records
    duplicate mapping keys instead of silently keeping the last one.
    """
    def __init__(self, stream):
        super().__init__(stream)
        self.errors: list[FieldError] = []

    def construct_located_map(self, node: yaml.MappingNode):
        data = LocatedDict()
        data.line = _line(node)
        yield data
        explicit = [
            (k, v) for k, v in node.value
            if k.tag != "tag:yaml.org,2002:merge"
        ]
        self.flatten_mapping(node)
        merged = node.value[:len(node.value) - len(explicit)]
        for key_node, value_node in merged:
            key = self.construct_object(key_node, deep=True)
            try:
                hash(key)
            except TypeError:
                self.errors.append(FieldError(
                    "", _line(key_node), "mapping keys must be scalars"))
                continue
            data[key] = self.construct_object(value_node)
            data.key_lines[key] = _line(key_node)
            data.value_lines[key] = _line(value_node)
        seen: dict[Any, int] = {}
        for key_node, value_node in explicit:
            key = self.construct_object(key_node, deep=True)
            try:
                hash(key)
            except TypeError:
                self.errors.append(FieldError(
                    "", _line(key_node), "mapping keys must be scalars"))
                continue
            if key in seen:
                self.errors.append(FieldError(
                    "", _line(key_node),
                    f"duplicate key {key!r} (first set on line {seen[key]})"))
                continue
            seen[key] = _line(key_node)
            data[key] = self.construct_object(value_node)
            data.key_lines[key] = _line(key_node)
            data.value_lines[key] = _line(value_node)

    def construct_located_seq(self, node: yaml.SequenceNode):
        data = LocatedList()
        data.line = _line(node)
        yield data
        data.extend(self.construct_object(child) for child in node.value)
        data.item_lines = [_line(child) for child in node.value]


LocatingLoader.add_constructor(
    "tag:yaml.org,2002:map", LocatingLoader.construct_located_map)
LocatingLoader.add_constructor(
    "tag:yaml.org,2002:seq", LocatingLoader.construct_located_seq)


def parse(stream, filename: str | None = None) -> tuple[Any, list[FieldError]]:
    """
    Parse a single YAML document, keeping line information. Problems that
    don't prevent parsing (such as duplicate keys) are returned rather than
    raised, so that they can be reported along with validation errors.

    :raises ValidationError: on YAML syntax errors
    """
    loader = None
    try:
        # The reader checks for invalid characters as soon as it's created
        loader = LocatingLoader(stream)
        data = loader.get_single_data()
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        line = mark.line + 1 if mark else None
        problem = exc.problem or exc.context or str(exc)
        raise ValidationError(
            [FieldError("", line, f"invalid YAML: {problem}")], filename)
    except yaml.YAMLError as exc:
        raise ValidationError(
            [FieldError("", None, f"invalid YAML: {exc}")], filename)
    finally:
        if loader is not None:
            loader.dispose()
    return data, loader.errors


def load(stream, filename: str | None = None) -> Any:
    """
    Parse a single YAML document, keeping line information.

    :raises ValidationError: on YAML syntax errors or duplicate keys
    """
    data, errors = parse(stream, filename)
    if errors:
        raise ValidationError(errors, filename)
    return data


@dataclass
class Location:
    """Where a dataclass instance and each of its fields came from."""
    path: str
    line: int | None
    field_lines: dict[str, int] = field(default_factory=dict)
    field_keys: dict[str, str] = field(default_factory=dict)

    def child(self, name: str) -> str:
        return join_path(self.path, name)


_LOCATION_ATTR = "_yamlclass_location"


def location(obj: Any) -> Location | None:
    """Return the Location recorded for an instance built by from_yaml()."""
    return getattr(obj, _LOCATION_ATTR, None)


def join_path(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def index_path(path: str, index: int) -> str:
    return f"{path}[{index}]"


class Context:
    """Passed to yaml_validate() to report errors against an instance."""
    def __init__(self, errors: list[FieldError], loc: Location):
        self._errors = errors
        self.location = loc

    def error(self, message: str, *, field: str | None = None,
              path: str | None = None, line: int | None = None) -> None:
        """
        Report a problem. By default it is reported against the instance;
        pass ``field`` to report it against one of its fields, or ``path`` and
        ``line`` to report it anywhere.
        """
        if path is None:
            if field:
                # Use the key as written, which may be an alias
                path = self.location.child(
                    self.location.field_keys.get(field, field))
            else:
                path = self.location.path
        if line is None:
            if field and field in self.location.field_lines:
                line = self.location.field_lines[field]
            else:
                line = self.location.line
        self._errors.append(FieldError(path, line, message))


def normalize_key(key: str) -> str:
    return key.replace("-", "_")


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "mapping"
    if isinstance(value, list):
        return "list"
    return type(value).__name__


def _describe(tp: Any) -> str:
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        return " or ".join(_describe(a) for a in args)
    if origin is list:
        (item,) = typing.get_args(tp)
        return f"a list of {_plural(item)}"
    if dataclasses.is_dataclass(tp):
        return "a mapping"
    return {str: "a string", int: "an integer", bool: "a boolean"}.get(
        tp, getattr(tp, "__name__", str(tp)))


def _plural(tp: Any) -> str:
    return {str: "strings", int: "integers", bool: "booleans"}.get(
        tp, "mappings" if dataclasses.is_dataclass(tp) else _describe(tp))


class _Converter:
    def __init__(self):
        self.errors: list[FieldError] = []

    def error(self, path: str, line: int | None, message: str) -> None:
        self.errors.append(FieldError(path, line, message))

    def convert(self, tp: Any, value: Any, path: str,
                line: int | None) -> Any:
        """Return the converted value, or _MISSING after reporting errors."""
        origin = typing.get_origin(tp)
        if origin in (typing.Union, types.UnionType):
            args = typing.get_args(tp)
            if value is None and type(None) in args:
                return None
            others = [a for a in args if a is not type(None)]
            if len(others) != 1:
                raise TypeError(f"unsupported union type {tp!r}")
            return self.convert(others[0], value, path, line)
        if origin is list:
            (item_tp,) = typing.get_args(tp)
            if not isinstance(value, list):
                return self._wrong_type(tp, value, path, line)
            item_lines = getattr(value, "item_lines", [])
            result = []
            ok = True
            for i, item in enumerate(value):
                item_line = item_lines[i] if i < len(item_lines) else line
                converted = self.convert(
                    item_tp, item, index_path(path, i), item_line)
                if converted is _MISSING:
                    ok = False
                result.append(converted)
            return result if ok else _MISSING
        if dataclasses.is_dataclass(tp):
            if not isinstance(value, dict):
                return self._wrong_type(tp, value, path, line)
            return self.build(tp, value, path)
        if tp is bool:
            if isinstance(value, bool):
                return value
            return self._wrong_type(tp, value, path, line)
        if tp is int:
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            return self._wrong_type(tp, value, path, line)
        if tp is str:
            if isinstance(value, str):
                return value
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                self.error(path, line,
                           f"expected a string, got {_type_name(value)} "
                           f"{value!r}; quote it in YAML, e.g. \"{value}\"")
                return _MISSING
            return self._wrong_type(tp, value, path, line)
        raise TypeError(f"unsupported field type {tp!r}")

    def _wrong_type(self, tp, value, path, line):
        got = _type_name(value)
        if value is not None and not isinstance(value, (dict, list)):
            got = f"{got} {value!r}"
        self.error(path, line, f"expected {_describe(tp)}, got {got}")
        return _MISSING

    def build(self, cls: type[T], data: dict, path: str) -> Any:
        mapping_line = getattr(data, "line", None)
        key_lines = getattr(data, "key_lines", {})
        value_lines = getattr(data, "value_lines", {})
        hints = typing.get_type_hints(cls)
        fields = {f.name: f for f in dataclasses.fields(cls) if f.init}
        by_key: dict[str, str] = {}
        for f in fields.values():
            by_key[f.name] = f.name
            for alias in f.metadata.get("aliases", ()):
                by_key[normalize_key(alias)] = f.name
        forbidden = {
            normalize_key(k): v
            for k, v in getattr(cls, "yaml_forbidden", {}).items()
        }

        loc = Location(path, mapping_line)
        raw: dict[str, tuple[str, Any]] = {}
        ok = True
        for key, value in data.items():
            key_line = key_lines.get(key, mapping_line)
            if not isinstance(key, str):
                self.error(path, key_line,
                           f"keys must be strings, got {_type_name(key)} "
                           f"{key!r}")
                ok = False
                continue
            norm = normalize_key(key)
            name = by_key.get(norm)
            if name is None:
                if norm in forbidden:
                    message = forbidden[norm]
                else:
                    message = f"unknown key {key!r}"
                    close = difflib.get_close_matches(
                        norm, list(by_key), n=1, cutoff=0.6)
                    if close:
                        message += f"; did you mean {close[0]!r}?"
                self.error(join_path(path, key), key_line, message)
                ok = False
                continue
            if name in raw:
                self.error(join_path(path, key), key_line,
                           f"{key!r} and {raw[name][0]!r} both set "
                           f"{name!r}; use only one")
                ok = False
                continue
            raw[name] = (key, value)
            loc.field_lines[name] = value_lines.get(key, key_line)
            loc.field_keys[name] = key

        kwargs = {}
        for name, f in fields.items():
            if name not in raw:
                if (f.default is dataclasses.MISSING
                        and f.default_factory is dataclasses.MISSING):
                    self.error(path, mapping_line,
                               f"missing required key {name!r}")
                    ok = False
                continue
            key, value = raw[name]
            field_path = join_path(path, key)
            line = loc.field_lines[name]
            coerce: Callable | None = f.metadata.get("coerce")
            if coerce is not None and value is not None:
                try:
                    value = coerce(value)
                except ValueError as exc:
                    self.error(field_path, line, str(exc))
                    ok = False
                    continue
            converted = self.convert(hints[name], value, field_path, line)
            if converted is _MISSING:
                ok = False
                continue
            check: Callable | None = f.metadata.get("check")
            if check is not None and converted is not None:
                message = check(converted)
                if message:
                    self.error(field_path, line, message)
                    ok = False
                    continue
            kwargs[name] = converted

        if not ok:
            return _MISSING
        instance = cls(**kwargs)
        object.__setattr__(instance, _LOCATION_ATTR, loc)
        validate = getattr(instance, "yaml_validate", None)
        if validate is not None:
            before = len(self.errors)
            validate(Context(self.errors, loc))
            if len(self.errors) > before:
                return _MISSING
        return instance


def from_yaml(cls: type[T], data: Any, *, filename: str | None = None,
              path: str = "", errors: list[FieldError] | None = None) -> T:
    """
    Build an instance of the dataclass ``cls`` from loaded YAML data.

    :param errors: Problems found earlier (e.g. by parse()) to report along
                   with any found here
    :raises ValidationError: listing every problem found
    """
    converter = _Converter()
    converter.errors.extend(errors or [])
    if not isinstance(data, dict):
        line = getattr(data, "line", None)
        got = "an empty document" if data is None else _type_name(data)
        converter.error(path, line, f"expected a mapping, got {got}")
        raise ValidationError(converter.errors, filename)
    result = converter.build(cls, data, path)
    if converter.errors or result is _MISSING:
        raise ValidationError(converter.errors, filename)
    return result
