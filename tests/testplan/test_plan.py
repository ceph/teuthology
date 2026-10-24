import textwrap

import pytest

from teuthology.testplan import plan
from teuthology.testplan.plan import COMMAND_LINE_KEYS, ValidationError


def loads(text):
    return plan.loads(textwrap.dedent(text), filename="p.yaml")


def errors_of(text):
    with pytest.raises(ValidationError) as exc:
        loads(text)
    return str(exc.value).splitlines()


def test_minimal():
    p = loads("""\
        name: smoke
        runs:
        - suite: rados
        """)
    assert p.name == "smoke"
    assert p.filename == "p.yaml"
    assert len(p.sha256) == 64
    (run,) = p.resolved_runs()
    assert run.suite == "rados"
    assert run.settings == {}


def test_defaults_merge_and_sources():
    p = loads("""\
        name: smoke
        defaults:
          limit: 20
          filter-out: crimson, seastore
          os_type: centos
        runs:
        - suite: rbd/basic/
          distro: ubuntu
          distro_version: "22.04"
        - suite: rados
          limit: 5
        """)
    first, second = p.resolved_runs()
    assert first.suite_name == "rbd:basic"
    assert first.settings == {
        "limit": 20,
        "filter_out": ["crimson", "seastore"],
        "distro": "ubuntu",
        "distro_version": "22.04",
    }
    assert first.sources["limit"] == plan.Source("defaults.limit", 3)
    assert first.sources["filter_out"] == plan.Source(
        "defaults.filter-out", 4)
    assert first.sources["distro"] == plan.Source("runs[0].distro", 8)
    assert second.settings == {
        "limit": 5,
        "filter_out": ["crimson", "seastore"],
        "distro": "centos",
    }
    assert second.sources["limit"] == plan.Source("runs[1].limit", 11)
    assert (first.line, second.line) == (7, 10)


def test_all_errors_reported():
    assert errors_of("""\
        name: bad name
        bogus: 1
        defaults:
          suite: rados
          distro_version: 22.04
        runs:
        - suite: /rados
          subset: 5/3
          filtr: thrash
          machine_type: smithi
          num: 3
          filter_out: crimson, ,x
          seed: -1
        - suite: rbd/../x
          label: has-dash
          limit: true
        - suite: fs
          limit: 3
          limit: 4
        """) == [
        "p.yaml:1: name: must start with a letter or digit and contain only "
        "letters, digits, '.', '_' and '-'",
        "p.yaml:2: bogus: unknown key 'bogus'",
        "p.yaml:4: defaults.suite: 'suite' must be set on each run, not in "
        "defaults",
        "p.yaml:5: defaults.distro_version: expected a string, got number "
        "22.04; quote it in YAML, e.g. \"22.04\"",
        "p.yaml:7: runs[0].suite: must be relative to the suites directory, "
        "e.g. 'rados/basic'",
        "p.yaml:8: runs[0].subset: expected 'N/M' with 0 <= N < M, got '5/3'",
        "p.yaml:9: runs[0].filtr: unknown key 'filtr'; did you mean "
        "'filter'?",
        "p.yaml:10: runs[0].machine_type: 'machine_type' can't be set in a "
        "testplan; pass --machine-type to 'teuthology-testplan run' instead",
        "p.yaml:11: runs[0].num: 'num' is not supported in testplans",
        "p.yaml:12: runs[0].filter_out: keywords must not be empty",
        "p.yaml:13: runs[0].seed: must be 0 or greater, got -1",
        "p.yaml:14: runs[1].suite: 'rbd/../x' is not a valid suite path",
        "p.yaml:15: runs[1].label: must start with a letter and contain "
        "only letters, digits, '.' and '_' (it becomes part of the run name)",
        "p.yaml:16: runs[1].limit: expected an integer, got boolean True",
        "p.yaml:19: duplicate key 'limit' (first set on line 18)",
    ]


@pytest.mark.parametrize("key", sorted(COMMAND_LINE_KEYS))
def test_command_line_keys_rejected(key):
    (error,) = errors_of(f"""\
        name: smoke
        runs:
        - suite: rados
          {key}: x
        """)
    assert f"pass {COMMAND_LINE_KEYS[key]} to" in error


def test_required_keys():
    assert errors_of("""\
        description: nothing
        runs:
        - label: x
        """) == [
        "p.yaml:1: missing required key 'name'",
        "p.yaml:3: runs[0]: missing required key 'suite'",
    ]


def test_runs_not_empty():
    assert errors_of("name: x\nruns: []\n") == [
        "p.yaml:2: runs: must list at least one run"]


@pytest.mark.parametrize("subset, ok", [
    ("0/1", True), ("3/4", True), ("1/1", False), ("1", False),
    ("a/b", False), ("-1/2", False),
])
def test_subset(subset, ok):
    text = f"name: x\nruns:\n- suite: s\n  subset: '{subset}'\n"
    if ok:
        assert loads(text).runs[0].subset == subset
    else:
        errors_of(text)


def test_duplicate_labels():
    assert errors_of("""\
        name: x
        runs:
        - suite: a
          label: one
        - suite: b
          label: one
        """) == [
        "p.yaml:6: runs[1].label: label 'one' is already used by runs[0]"]


def test_identical_runs():
    assert errors_of("""\
        name: x
        defaults:
          limit: 3
        runs:
        - suite: rados/basic
        - suite: rados:basic
          limit: 3
        """) == [
        "p.yaml:6: runs[1]: identical to runs[0] (line 5); remove it, or "
        "give both runs a label"]


def test_identical_runs_allowed_with_labels():
    p = loads("""\
        name: x
        runs:
        - suite: rados
          label: a
        - suite: rados
          label: b
        """)
    assert [r.ident for r in p.resolved_runs()] == ["a", "b"]


def test_distro_version_requires_distro():
    assert errors_of("""\
        name: x
        defaults:
          distro_version: "22.04"
        runs:
        - suite: a
          distro: ubuntu
        - suite: b
        - suite: c
          os_version: "9"
        """) == [
        "p.yaml:7: runs[1]: distro_version from defaults requires distro",
        "p.yaml:9: runs[2].os_version: distro_version requires distro (in "
        "this run or in defaults)",
    ]


def test_label_cannot_look_like_a_run_number():
    # Unlabeled runs are told apart by number, e.g. 'rados.1'
    (error,) = errors_of("""\
        name: x
        runs:
        - suite: rados
          label: "1"
        - suite: rados
        """)
    assert error.startswith("p.yaml:4: runs[0].label: must start with a "
                            "letter")


def test_unknown_distro_version():
    assert errors_of("""\
        name: x
        defaults:
          distro: ubuntu
        runs:
        - suite: a
          distro_version: "22.04"
        - suite: b
          os_version: "1.0"
        - suite: c
          distro: centos
          distro_version: jammy
        """) == [
        "p.yaml:8: runs[1].os_version: '1.0' is not a known ubuntu version "
        "or codename",
        "p.yaml:11: runs[2].distro_version: 'jammy' is not a known centos "
        "version or codename",
    ]


def test_distro_codename_accepted():
    p = loads("name: x\nruns:\n- suite: a\n  distro: ubuntu\n"
              "  distro_version: jammy\n")
    assert p.runs[0].distro_version == "jammy"


def test_sha256_is_of_file_bytes(tmp_path):
    import hashlib
    raw = b"name: x\r\nruns:\r\n- suite: a\r\n"
    path = tmp_path / "crlf.yaml"
    path.write_bytes(raw)
    assert plan.load(str(path)).sha256 == hashlib.sha256(raw).hexdigest()


def test_not_utf8(tmp_path):
    path = tmp_path / "latin1.yaml"
    path.write_bytes(b"name: caf\xe9\nruns:\n- suite: a\n")
    with pytest.raises(ValidationError) as exc:
        plan.load(str(path))
    assert str(exc.value).startswith(f"{path}: not valid UTF-8: ")


def test_filters_accept_lists_and_strings():
    p = loads("""\
        name: x
        runs:
        - suite: a
          filter: [one, two]
          filter_all: " one , two "
        """)
    assert p.runs[0].filter == ["one", "two"]
    assert p.runs[0].filter_all == ["one", "two"]
