import logging

from teuthology.util import redmine_suggest


def test_failure_search_query():
    assert redmine_suggest.failure_search_query("") == ""
    long = "a " * 150
    q = redmine_suggest.failure_search_query(long, max_len=20)
    assert len(q) <= 20


def test_normalize_failure_text_for_search_removes_host_noise():
    text = (
        "Command failed on ip-a-b-c-d with status 100: "
        "'sudo DEBIAN_FRONTEND=noninteractive apt-get -y install linux-image-generic'"
    )
    out = redmine_suggest.normalize_failure_text_for_search(text)
    assert "ip-a-b-c-d" not in out
    assert "DEBIAN_FRONTEND=noninteractive" not in out
    assert "sudo " not in out
    assert "apt-get -y install linux-image-generic" in out


def test_normalize_failure_text_for_search_handles_other_host_formats():
    text = (
        "Command failed on 10.20.30.40 with status 1: "
        "'sudo curl https://node1.example.com/api/health'"
    )
    out = redmine_suggest.normalize_failure_text_for_search(text)
    assert "10.20.30.40" not in out
    assert "node1.example.com" not in out
    assert "host/api/health" in out


def test_normalize_failure_text_for_search_handles_plain_hostnames():
    text = "Command failed on trial011 with status 1: 'sudo ceph -s'"
    out = redmine_suggest.normalize_failure_text_for_search(text)
    assert "trial011" not in out
    assert "Command failed with status 1" in out


def test_combined_failure_text_prefers_detail():
    combined = redmine_suggest.combined_failure_text(
        "reached maximum tries (50) after waiting for 300 seconds",
        "Command failed on node with status 1: 'sudo ceph osd pool create rbd 8'",
    )
    assert combined.startswith("Command failed on node")
    assert "caused by: reached maximum tries" not in combined


def test_combined_failure_text_uses_reason_when_not_timeout():
    combined = redmine_suggest.combined_failure_text(
        "command exited with non-zero status",
        "Command failed on node with status 1",
    )
    assert "caused by: command exited with non-zero status" in combined


def test_combined_failure_text_adds_timeout_command_hint():
    combined = redmine_suggest.combined_failure_text(
        "status 124:  timeout 3h /home/ubuntu/cephtest/workunit.client.0/qa/workunits/rados/test.sh'",
        "",
    )
    assert "timeout 3h running qa/workunits/rados/test.sh" in combined


def test_is_generic_timeout_reason():
    assert redmine_suggest.is_generic_timeout_reason(
        "reached maximum tries (50) after waiting for 300 seconds"
    )
    assert redmine_suggest.is_generic_timeout_reason("hit max job timeout")
    assert not redmine_suggest.is_generic_timeout_reason(
        "Command failed on node with status 1"
    )


def test_extract_log_failure_hint_gtest(tmpdir):
    p = tmpdir.join("teuthology.log")
    p.write(
        "\n".join(
            [
                "[ RUN      ] TestMigration.Stress2",
                "[  FAILED  ] TestMigration.Stress2 (24944 ms)",
            ]
        )
    )
    hint = redmine_suggest.extract_log_failure_hint(str(p))
    assert hint == "failed test: TestMigration.Stress2"


def test_issue_id_from_search_result():
    iid = redmine_suggest._issue_id_from_search_result(
        {"url": "https://tracker.ceph.com/issues/12345", "title": "x", "type": "issue"}
    )
    assert iid == 12345
    iid2 = redmine_suggest._issue_id_from_search_result(
        {"title": "Issue #99 (Closed): hello", "type": "issue closed"}
    )
    assert iid2 == 99


def test_redmine_search_issue_ids(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "results": [
                    {
                        "id": 1,
                        "title": "Issue #1: T",
                        "type": "issue",
                        "url": "https://tracker.ceph.com/issues/1",
                    },
                    {
                        "id": 2,
                        "title": "Wiki",
                        "type": "wiki-page",
                        "url": "https://tracker.ceph.com/wiki/x",
                    },
                ]
            }

    def fake_get(url, params, timeout):
        assert "search.json" in url
        assert params.get("issues") == 1
        return FakeResp()

    monkeypatch.setattr(redmine_suggest.requests, "get", fake_get)
    out = redmine_suggest.redmine_search_issue_ids(
        "https://tracker.ceph.com", "query", limit=5
    )
    assert out == [(1, "Issue #1: T")]


def test_log_redmine_suggestions_no_hits(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(
        redmine_suggest,
        "redmine_search_issue_ids",
        lambda base_url, query, limit=8: [],
    )
    redmine_suggest.log_redmine_suggestions_on_failure(
        logging.getLogger("t"),
        "some failure",
        {},
    )
    assert not caplog.records


def test_log_redmine_suggestions_uses_failure_reason_detail(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(
        redmine_suggest,
        "redmine_search_issue_ids",
        lambda base_url, query, limit=8: [(77, "Issue 77")],
    )
    redmine_suggest.log_redmine_suggestions_on_failure(
        logging.getLogger("t"),
        "reached maximum tries (50) after waiting for 300 seconds",
        {"redmine_base_url": "https://tracker.ceph.com"},
        failure_reason_detail=(
            "Command failed on node with status 1: "
            "'sudo ceph --cluster ceph osd pool create rbd 8'"
        ),
    )
    assert any("#77" in r.message for r in caplog.records)


def test_log_redmine_suggestions_uses_log_failure_hint(caplog, tmpdir, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(
        redmine_suggest,
        "redmine_search_issue_ids",
        lambda base_url, query, limit=8: [(88, "Issue 88")],
    )
    teuthology_log = tmpdir.join("teuthology.log")
    teuthology_log.write(
        "\n".join(
            [
                "[ RUN      ] TestMigration.Stress2",
                "[  FAILED  ] TestMigration.Stress2 (24944 ms)",
                "1 FAILED TEST",
            ]
        )
    )
    redmine_suggest.log_redmine_suggestions_on_failure(
        logging.getLogger("t"),
        "reached maximum tries (50) after waiting for 300 seconds",
        {"redmine_base_url": "https://tracker.ceph.com"},
        teuthology_log_path=str(teuthology_log),
    )
    assert any("#88" in r.message for r in caplog.records)


def test_log_redmine_suggestions_searches_without_api_key(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(
        redmine_suggest,
        "redmine_search_issue_ids",
        lambda base_url, query, limit=8: [(99, "Issue without key")],
    )
    redmine_suggest.log_redmine_suggestions_on_failure(
        logging.getLogger("t"),
        "some failure",
        {"redmine_base_url": "https://tracker.ceph.com"},
    )
    assert any("#99" in r.message for r in caplog.records)
