"""
Suggest Redmine / tracker issue IDs when a job fails.

Redmine search API — ``GET .../search.json?q=...&issues=1`` uses a normalized
excerpt of failure text as full-text query and logs candidate issues.

Enable from job YAML::

    redmine_base_url: https://tracker.ceph.com
    redmine_search_limit: 5
"""

import logging
import os
import re

import requests

from teuthology.scrape import TimeoutReason

log = logging.getLogger(__name__)


_GENERIC_TIMEOUT_PATTERNS = [
    r"reached maximum tries \(\d+\) after waiting for \d+ seconds",
    r"hit max job timeout",
    r"authenticate timed out after \d+",
    r"\boperation timed out\b",
    r"\bconnection timed out\b",
]


def _normalize_base_url(url):
    return url.rstrip("/")


def normalize_failure_text_for_search(text):
    """
    Normalize failure text tokens so similar failures map to similar queries.
    """
    if not text:
        return ""
    out = " ".join(text.split())
    out = re.sub(
        r"\bon\s+(?:"
        r"(?:\d{1,3}\.){3}\d{1,3}|"
        r"[A-Za-z0-9._-]+"
        r")(?=\s+with status\b)",
        "",
        out,
        flags=re.IGNORECASE,
    )
    # remove noisy environment assignments from cli
    out = re.sub(r"\b[A-Z_][A-Z0-9_]*=(?:\"[^\"]*\"|'[^']*'|\S+)", "", out)
    # Replace host-like tokens so search is less tied to one run.
    out = re.sub(r"\bip-\d+(?:-\d+){3}\b", "host", out)
    out = re.sub(r"\bnode\d+\b", "host", out)
    out = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "host", out)
    out = re.sub(r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+\b", "host", out, flags=re.IGNORECASE)
    # Keep command core by dropping leading sudo in cmd snippets
    out = re.sub(r"(?<!\w)sudo\s+", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out)
    # Clean up truncated quote artifacts at query boundary
    out = out.replace("''", "'")
    return out.strip(" '\"|:")


def failure_search_query(failure_reason, max_len=200):
    """Build a Redmine ``q`` parameter from free-text failure output."""
    if not failure_reason:
        return ""
    one_line = normalize_failure_text_for_search(failure_reason)
    return one_line[:max_len]


def combined_failure_text(
    failure_reason,
    failure_reason_detail=None,
    log_failure_hint=None,
):
    """
    Build matching/search text from summary fields.

    `failure_reason_detail` (if present) is preferred because it often
    contains the actionable inner exception while `failure_reason` can be
    generic (like timeout wrapper).
    """
    reason = (failure_reason or "").strip()
    detail = (failure_reason_detail or "").strip()
    hint = (log_failure_hint or "").strip()
    reason_is_timeout = is_generic_timeout_reason(reason)
    timeout_data = extract_timeout_command_from_scrape(detail) or extract_timeout_command_from_scrape(reason)

    parts = []
    if timeout_data:
        timeout, command = timeout_data
        parts.append("timeout %s running %s" % (timeout, command))
    if hint:
        parts.append(hint)
    if detail and detail != hint:
        parts.append(detail)
    if reason and not reason_is_timeout and reason != detail and reason != hint:
        parts.append("caused by: %s" % reason if (hint or detail) else reason)
    return " | ".join(parts)


class _FailureReasonOnlyJob(object):
    def __init__(self, failure_reason):
        self._failure_reason = failure_reason

    def get_failure_reason(self):
        return self._failure_reason


def extract_timeout_command_from_scrape(failure_reason):
    if not failure_reason:
        return None
    return TimeoutReason.get_timeout(_FailureReasonOnlyJob(failure_reason))


def is_generic_timeout_reason(text):
    text = (text or "").strip().lower()
    if not text:
        return False
    return any(re.search(pat, text) for pat in _GENERIC_TIMEOUT_PATTERNS)


def extract_log_failure_hint(
    teuthology_log_path, max_scan_bytes=20_000_000
):
    """
    Extract a compact, high-signal failure hint from `teuthology.log`.

    This is a best-effort fallback for runs where summary/exception text is too
    generic. The parser scans from the end of the log for common test-failure
    markers.
    """
    if not teuthology_log_path:
        return None
    try:
        with open(teuthology_log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - max_scan_bytes)
            f.seek(start)
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None

    patterns = [
        (r"\[\s*FAILED\s*\]\s+([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)\b", "failed test: %s"),
        (r"(?m)^\s*FAILED\s+([^\s]+::[^\s]+)\s*$", "failed test: %s"),
        (r"(?m)^\s*FAIL:\s+([A-Za-z0-9_./:-]+)\s*$", "failed test: %s"),
    ]
    for pattern, fmt in patterns:
        matches = re.findall(pattern, text)
        if matches:
            return fmt % matches[-1]
    return None


def _issue_id_from_search_result(item):
    url = item.get("url") or ""
    m = re.search(r"/issues/(\d+)", url)
    if m:
        return int(m.group(1))
    title = item.get("title") or ""
    m = re.search(r"#(\d+)", title)
    if m:
        return int(m.group(1))
    rid = item.get("id")
    if isinstance(rid, int) and item.get("type", "").startswith("issue"):
        return rid
    return None


def redmine_search_issue_ids(
    base_url,
    query,
    limit=8,
    timeout=20.0,
):
    """
    Call Redmine ``/search.json`` and return (issue_id, title) pairs.

    :returns: list of tuples; empty on error or empty query.
    """
    if not query.strip():
        return []
    url = _normalize_base_url(base_url) + "/search.json"
    params = {"q": query, "issues": 1, "limit": max(1, min(limit, 100))}
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning("Redmine search failed: %s", e)
        return []
    try:
        payload = resp.json()
    except ValueError:
        log.warning("Redmine search returned non-JSON")
        return []
    results = payload.get("results") or []
    out = []
    for item in results:
        if not isinstance(item, dict):
            continue
        type_s = str(item.get("type") or "")
        if "issue" not in type_s.lower():
            continue
        iid = _issue_id_from_search_result(item)
        if iid is None:
            continue
        title = str(item.get("title") or "").replace("\n", " ")[:120]
        out.append((iid, title))
    return out


def log_redmine_suggestions_on_failure(
    logger,
    failure_reason,
    cfg,
    failure_reason_detail=None,
    teuthology_log_path=None,
):
    """
    Log possible tracker issue IDs after the summary block (teuthology.log).

    `cfg` is the full job config mapping.
    """
    if not cfg or not isinstance(cfg, dict):
        return
    log_failure_hint = extract_log_failure_hint(teuthology_log_path)
    reason = combined_failure_text(
        failure_reason,
        failure_reason_detail,
        log_failure_hint=log_failure_hint,
    )

    base_url = (
        cfg.get("redmine_base_url")
        or "https://tracker.ceph.com"
    )
    search_limit = int(cfg.get("redmine_search_limit", 5))

    if not base_url:
        logger.debug("redmine-on-failure: no base_url; skipping Redmine search")
        return

    q = failure_search_query(reason)
    hits = redmine_search_issue_ids(
        str(base_url), q, limit=search_limit
    )
    if not hits:
        return

    parts = []
    seen_ids = set()
    for i, t in hits:
        if i in seen_ids:
            continue
        seen_ids.add(i)
        parts.append("#%d: %s" % (i, t))
    if parts:
        logger.info("Possible tracker issues (Redmine search): %s", " | ".join(parts))
