import textwrap

from dataclasses import dataclass, field
from typing import ClassVar

import pytest

from teuthology.util import yamlclass
from teuthology.util.yamlclass import (
    FieldError, LocatedDict, LocatedList, ValidationError,
)


def parse(text):
    return yamlclass.load(textwrap.dedent(text))


def check_positive(value):
    if value <= 0:
        return "must be positive"
    return None


def split_commas(value):
    if isinstance(value, str):
        if value == "bad":
            raise ValueError("'bad' is not allowed")
        return value.split(",")
    return value


@dataclass(kw_only=True)
class Item:
    name: str
    count: int | None = field(default=None, metadata={"check": check_positive})


@dataclass(kw_only=True)
class Doc:
    yaml_forbidden: ClassVar[dict[str, str]] = {
        "secret": "secrets don't belong here",
    }

    title: str
    enabled: bool = False
    color: str | None = field(default=None, metadata={"aliases": ("colour",)})
    tags: list[str] | None = field(default=None, metadata={
        "coerce": split_commas})
    items: list[Item] = field(default_factory=list)
    child: Item | None = None

    def yaml_validate(self, ctx):
        if self.color == "clash" and self.enabled:
            ctx.error("clash can't be enabled", field="color")


def errors_of(cls, text):
    with pytest.raises(ValidationError) as exc:
        yamlclass.from_yaml(cls, parse(text), filename="f.yaml")
    return [e.format("f.yaml") for e in exc.value.errors]


class TestLoad:
    def test_located_containers(self):
        data = parse("""\
            a: 1
            b:
              - x
              - y: 2
            """)
        assert isinstance(data, LocatedDict)
        assert data.line == 1
        assert data.key_lines == {"a": 1, "b": 2}
        assert data.value_lines == {"a": 1, "b": 3}
        assert isinstance(data["b"], LocatedList)
        assert data["b"].item_lines == [3, 4]
        assert data["b"][1].line == 4
        assert data == {"a": 1, "b": ["x", {"y": 2}]}

    def test_duplicate_keys(self):
        with pytest.raises(ValidationError) as exc:
            parse("""\
                a: 1
                b: 2
                a: 3
                """)
        assert exc.value.errors == [
            FieldError("", 3, "duplicate key 'a' (first set on line 1)")]

    def test_merge_keys_may_be_overridden(self):
        data = parse("""\
            base: &base {a: 1, b: 2}
            other:
              <<: *base
              b: 3
            """)
        assert data["other"] == {"a": 1, "b": 3}
        assert data["other"].value_lines["b"] == 4

    def test_syntax_error(self):
        with pytest.raises(ValidationError) as exc:
            yamlclass.load("a: [1, 2\nb: 3\n", filename="f.yaml")
        (error,) = exc.value.errors
        assert error.line is not None
        assert error.message.startswith("invalid YAML: ")
        assert str(exc.value).startswith("f.yaml:")

    def test_reader_error(self):
        # Control characters fail in the reader, before any marks exist
        with pytest.raises(ValidationError) as exc:
            yamlclass.load("a: \x07\n", filename="f.yaml")
        assert str(exc.value).startswith("f.yaml: invalid YAML: ")

    def test_unhashable_merged_key(self):
        with pytest.raises(ValidationError) as exc:
            parse("""\
                a:
                  <<: {? [1, 2] : x}
                  b: 1
                """)
        assert [e.message for e in exc.value.errors] == [
            "mapping keys must be scalars"]

    def test_parse_returns_duplicate_errors(self):
        data, errors = yamlclass.parse("a: 1\na: 2\n")
        assert data == {"a": 1}
        assert len(errors) == 1


class TestFromYaml:
    def test_valid(self):
        doc = yamlclass.from_yaml(Doc, parse("""\
            title: hello
            enabled: true
            colour: red
            tags: a,b
            items:
              - name: one
              - name: two
                count: 2
            child:
              name: kid
            """))
        assert doc == Doc(
            title="hello", enabled=True, color="red", tags=["a", "b"],
            items=[Item(name="one"), Item(name="two", count=2)],
            child=Item(name="kid"))
        loc = yamlclass.location(doc)
        assert loc.path == ""
        assert loc.field_lines["color"] == 3
        assert loc.field_keys["color"] == "colour"
        item_loc = yamlclass.location(doc.items[1])
        assert item_loc.path == "items[1]"
        assert item_loc.line == 7
        assert yamlclass.location(doc.child).path == "child"

    def test_hyphenated_keys(self):
        @dataclass
        class Opts:
            filter_out: str

        assert yamlclass.from_yaml(
            Opts, parse("filter-out: x\n")) == Opts(filter_out="x")

    def test_all_errors_reported_with_lines(self):
        assert errors_of(Doc, """\
            enabled: yes please
            colr: red
            secret: 1
            tags: [a, 1]
            items:
              - name: one
                count: 0
              - count: 2
            child: nope
            """) == [
            "f.yaml:1: missing required key 'title'",
            "f.yaml:1: enabled: expected a boolean, got string 'yes please'",
            "f.yaml:2: colr: unknown key 'colr'; did you mean 'color'?",
            "f.yaml:3: secret: secrets don't belong here",
            "f.yaml:4: tags[1]: expected a string, got integer 1; "
            "quote it in YAML, e.g. \"1\"",
            "f.yaml:7: items[0].count: must be positive",
            "f.yaml:8: items[1]: missing required key 'name'",
            "f.yaml:9: child: expected a mapping, got string 'nope'",
        ]

    def test_bool_is_not_int(self):
        assert errors_of(Item, "name: x\ncount: true\n") == [
            "f.yaml:2: count: expected an integer, got boolean True"]

    def test_float_for_string_suggests_quoting(self):
        assert errors_of(Item, "name: 22.04\n") == [
            "f.yaml:1: name: expected a string, got number 22.04; "
            "quote it in YAML, e.g. \"22.04\""]

    def test_null_for_required_type(self):
        assert errors_of(Item, "name:\n") == [
            "f.yaml:1: name: expected a string, got null"]

    def test_alias_and_name_both_set(self):
        assert errors_of(Doc, "title: t\ncolor: a\ncolour: b\n") == [
            "f.yaml:3: colour: 'colour' and 'color' both set 'color'; "
            "use only one"]

    def test_coerce_error(self):
        assert errors_of(Doc, "title: t\ntags: bad\n") == [
            "f.yaml:2: tags: 'bad' is not allowed"]

    def test_non_string_key(self):
        assert errors_of(Item, "name: x\n1: y\n") == [
            "f.yaml:2: keys must be strings, got integer 1"]

    def test_yaml_validate(self):
        assert errors_of(Doc, "title: t\nenabled: true\ncolor: clash\n") == [
            "f.yaml:3: color: clash can't be enabled"]

    def test_yaml_validate_reports_key_as_written(self):
        assert errors_of(Doc, "title: t\nenabled: true\ncolour: clash\n") == [
            "f.yaml:3: colour: clash can't be enabled"]

    def test_yaml_validate_skipped_when_fields_invalid(self):
        assert errors_of(
            Doc, "title: t\nenabled: true\ncolor: clash\nbogus: 1\n") == [
            "f.yaml:4: bogus: unknown key 'bogus'"]

    @pytest.mark.parametrize("text, expected", [
        ("", "f.yaml: expected a mapping, got an empty document"),
        ("- a\n", "f.yaml:1: expected a mapping, got list"),
    ])
    def test_document_must_be_mapping(self, text, expected):
        assert errors_of(Item, text) == [expected]

    def test_earlier_errors_included(self):
        data, errors = yamlclass.parse("name: x\nname: y\ncount: 0\n")
        with pytest.raises(ValidationError) as exc:
            yamlclass.from_yaml(Item, data, errors=errors)
        assert [e.message for e in exc.value.errors] == [
            "duplicate key 'name' (first set on line 1)",
            "must be positive",
        ]
