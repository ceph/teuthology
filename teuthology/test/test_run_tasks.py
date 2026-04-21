from teuthology import run_tasks


def test_first_nested_exception_message_from_context():
    try:
        try:
            raise RuntimeError("Command failed on node with status 1")
        except RuntimeError:
            raise ValueError("reached maximum tries (50) after waiting for 300 seconds")
    except ValueError as exc:
        detail = run_tasks._first_nested_exception_message(exc)
    assert detail == "Command failed on node with status 1"


def test_set_failure_reason_detail_if_missing_keeps_existing():
    summary = {"failure_reason_detail": "already set"}
    exc = RuntimeError("outer")
    run_tasks._set_failure_reason_detail_if_missing(summary, exc)
    assert summary["failure_reason_detail"] == "already set"
