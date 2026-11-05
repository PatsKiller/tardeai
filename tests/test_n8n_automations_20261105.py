"""Hermetic tests for the Automations projection (design automations/v001, APPROVED).

No database, no docker, no crontab: every source is handed in. The live numbers were checked by hand against the n8n DB
when the module was written (33 non-archived workflows, 2,988 runs / 2,920 failed in 7 days, 368 cron lines).
"""

import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("n8n_automations", ROOT / "scripts/lib/data_broker/n8n_automations.py")
M = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = M
spec.loader.exec_module(M)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def blob(message=None):
    """n8n's flattened execution_data: [{key: index}, …, values…], the error nested behind two indices."""
    flat = [
        {},
        {},
        {"error": "5", "runData": "6"},
        {},
        {},
        {"message": "17", "level": "14"},
        {},
        {},
        {},
        {},
        {},
        {},
        {},
        {},
        "error",
        {},
        {},
        message,
    ]
    return __import__("json").dumps(flat)


def wf(wid, name, active="f", archived="f", nodes="[{},{}]"):
    return {"raw": [wid, name, active, nodes, "2026-10-01T00:00:00Z", "2026-11-04T00:00:00Z", archived, ""]}


def ex(wid, status, started, stopped=None):
    return {"raw": [wid, status, started, stopped or ""]}


def test_psql_booleans_are_read_as_booleans():
    """psql -A prints `t`/`f`; reading only `true` made every workflow look off and unarchived (a real bug, fixed)."""
    rows = M.workflow_rows([wf("1", "a", active="t"), wf("2", "b", archived="t"), wf("3", "c", active="true")])
    assert rows[0]["active"] is True and rows[1]["archived"] is True and rows[2]["active"] is True


def test_the_error_message_is_resolved_through_the_flattened_indices():
    assert M.parse_error(blob("relay returned HTTP 403")) == "relay returned HTTP 403"
    assert M.parse_error("not json") is None
    assert M.parse_error(None) is None
    assert M.parse_error("[]") is None


def test_a_lock_skip_is_skipped_never_failed():
    assert M.classify("previous execution is still running (within SLA)") == "skipped"
    assert M.classify("relay returned HTTP 403: {reason: relay_live_not_enabled}") == "relay_refused"
    assert M.classify("Assert REQUESTED failed") == "failed"
    assert M.classify(None) == "unknown"


def test_the_payload_counts_and_ranks_and_never_invents_a_delta():
    workflows = M.workflow_rows([wf("1", "failing", active="t"), wf("2", "healthy"), wf("3", "old", archived="t")])
    stats = M.run_stats(
        [
            ex("1", "error", NOW - HOUR, NOW - HOUR + timedelta(seconds=2)),
            ex("1", "error", NOW - 2 * HOUR),
            ex("2", "success", NOW - HOUR, NOW - HOUR + timedelta(seconds=4)),
        ],
        NOW,
    )
    # cx-openai-5's F5 at 25b3348e: a crontab line is a JOB only when it has five schedule fields. An assignment
    # (`CRON_TZ=…`, `PATH=…`) is environment, not a job — one job plus one assignment is 1, not 2.
    out = M.summarize(
        workflows,
        stats,
        {"1": {"kind": "relay_refused", "one_line": "relay 403"}},
        now=NOW,
        cron_lines=["CRON_TZ=America/New_York", "*/5 * * * * /usr/bin/true", "0 9 * * 1-5 cd /x && ./y"],
        drafts=1,
    )
    assert out["counts"] == {"workflows": 2, "live": 1, "shadow": 0, "off": 1, "failing": 1}
    assert out["workflows"][0]["name"] == "failing" and out["workflows"][0]["fail"] == 2
    # cc-deepseek's F1 at 79ca2ac7e: this store keeps failures only, so 2 failed of 3 SAVED rows is not a failure rate.
    # The absolute counts stand; the percentage is withheld and says why.
    assert out["kpi"]["fail_rate_pct"] is None
    assert "stores failed runs only" in out["kpi"]["fail_rate_unavailable_reason"]
    assert out["workflows"][0]["fail_pct"] is None
    assert out["kpi"]["cron_left"] == 2 and out["kpi"]["cron_left_has_draft"] == 1
    assert out["kpi"]["deltas"] is None and "snapshot" in out["kpi"]["deltas_unavailable_reason"]


def test_the_failure_rate_is_never_derived_from_saved_rows_alone():
    """cc-deepseek's F1 at 79ca2ac7e (BLOCK). A fixture full of SAVED successes would make a ratio look sane while
    production returns almost none (EXECUTIONS_DATA_SAVE_ON_SUCCESS=none). The payload must not publish a rate at all,
    and must carry the reason — the same shape the week-over-week deltas already use."""
    wfs = [M.workflow_rows([{"raw": ["1", "w", "t", "[]", None, None, "f", None]}])[0]]
    rows = [ex("1", "success", NOW - 3 * HOUR)] * 50 + [ex("1", "error", NOW - 2 * HOUR)] * 2
    stats = M.run_stats(rows, NOW)
    out = M.summarize(wfs, stats, {}, now=NOW, cron_lines=[], drafts=0)
    assert out["kpi"]["ok"] == 50 and out["kpi"]["failed"] == 2  # the counts are real
    assert out["kpi"]["fail_rate_pct"] is None  # the ratio is not
    assert "by construction" in out["kpi"]["fail_rate_unavailable_reason"]


def test_the_query_guard_refuses_anything_that_is_not_a_select():
    with pytest.raises(ValueError):
        M.query_n8n("delete from workflow_entity")
    with pytest.raises(ValueError):
        M.query_n8n("update workflow_entity set active = false")


def test_the_query_guard_refuses_a_second_statement(monkeypatch):
    """cc-deepseek-9's F1 at d4bc7430.

    A prefix test cannot make a statement read-only: `select 1; drop table workflow_entity` starts with "select"
    and had no trailing semicolon to strip, so the old guard handed it to `psql -c`, which runs both. The refusal
    must happen BEFORE anything executes — asserted by making subprocess explode if it is ever reached.
    """

    def _boom(*_a, **_k):
        raise AssertionError("the guard passed a multi-statement to psql")

    monkeypatch.setattr(M.subprocess, "run", _boom)
    for sql in (
        "select 1; drop table workflow_entity",
        "select 1; drop table workflow_entity;",
        "select 1;;delete from workflow_entity",
        "select 'a;b'",
    ):
        with pytest.raises(ValueError):
            M.query_n8n(sql)


def test_a_single_select_with_one_trailing_semicolon_is_still_allowed(monkeypatch):
    """The refusal above must not refuse the query the lane actually runs."""
    captured = {}

    class Done:
        returncode = 0
        stdout = "1\t2\n"
        stderr = ""

    def _run(cmd, **_kw):
        captured["cmd"] = cmd
        return Done()

    monkeypatch.setattr(M.subprocess, "run", _run)
    rows = M.query_n8n("select workflow_id, name from workflow_entity;")
    assert rows == [{"raw": ["1", "2"]}]
    assert captured["cmd"][-1] == "select workflow_id, name from workflow_entity"
    assert "-e" in captured["cmd"] and any("default_transaction_read_only=on" in x for x in captured["cmd"])


def test_a_skipped_execution_is_counted_as_skipped_and_a_real_error_still_counts():
    """cx-openai-3's F1 / cx-openai-5's F1 at 25b3348e. Classifying the newest message is not a count repair: n8n
    records a lock skip as status='error', so the aggregation itself must know each execution's kind."""
    t1, t2, t3 = NOW - 3 * HOUR, NOW - 2 * HOUR, NOW - HOUR
    rows = [ex("1", "error", t1), ex("1", "error", t2), ex("1", "error", t3)]
    kinds = {("1", str(t2)): "skipped", ("1", str(t3)): "skipped", ("1", str(t1)): "failed"}
    stats = M.run_stats(rows, NOW, kinds=kinds)
    assert stats["per_workflow"]["1"]["failed"] == 1
    assert stats["per_workflow"]["1"]["skipped"] == 2
    assert stats["fleet"]["failed"] == 1 and stats["fleet"]["skipped"] == 2
    # one skip alone: no failure anywhere the page reads
    only = M.run_stats([ex("2", "error", t1)], NOW, kinds={("2", str(t1)): "skipped"})
    assert only["per_workflow"]["2"]["failed"] == 0
    out = M.summarize(M.workflow_rows([wf("2", "w2")]), only, {}, now=NOW, cron_lines=[], drafts=0)
    assert out["workflows"][0]["fail"] == 0 and out["counts"]["failing"] == 0
    assert out["workflows"][0]["skipped"] == 1 and out["kpi"]["skipped"] == 1


def test_the_producer_classifies_every_error_execution_not_only_the_newest():
    """The end-to-end path: get_automations reads each error execution's message, so a workflow whose newest error is
    a skip and whose older one is a real error still reports one failure."""
    t1, t2 = NOW - 2 * HOUR, NOW - HOUR

    def q(sql):
        if "from workflow_entity" in sql:
            return [wf("1", "w1")]
        if "from execution_entity e" in sql:
            # newest first: the skip is the newest
            return [
                {"raw": ["1", t2, blob("previous execution is still running (within SLA)")]},
                {"raw": ["1", t1, blob("Assert REQUESTED failed")]},
            ]
        return [ex("1", "error", t1), ex("1", "error", t2)]

    out = M.get_automations(query=q, now=NOW, cron=lambda: [], drafts=0)
    assert out["kpi"]["failed"] == 1 and out["kpi"]["skipped"] == 1
    assert out["workflows"][0]["fail"] == 1 and out["workflows"][0]["skipped"] == 1
    # cx-openai-5 at 22bb19504: with a real failure present the row names THAT, not the newer skip.
    assert out["workflows"][0]["last_error_kind"] == "failed"
    assert "REQUESTED" in (out["workflows"][0]["last_error"] or "")


def test_a_credential_shaped_error_never_reaches_the_payload():
    """cx-openai-3's F1 at 25b3348e: an HTTP node's failure can echo the request headers it was handed."""
    message = "Request failed: Authorization: Bearer SYNTHETIC_REVIEW_ONLY_CREDENTIAL"
    assert M.redact_secrets(message) == "Request failed: Authorization: Bearer [redacted]"
    assert "SYNTHETIC_REVIEW_ONLY_CREDENTIAL" not in (M.one_line(message) or "")
    assert "Request failed" in (M.one_line(message) or "")
    scrubbed = M.parse_error(blob(message))
    assert scrubbed is not None and "SYNTHETIC_REVIEW_ONLY_CREDENTIAL" not in scrubbed
    assert M.classify(scrubbed) == "failed"  # redaction does not change the classification
    assert M.redact_secrets("api_key=abcdef123456 and token: zzz999") == "api_key=[redacted] and token: [redacted]"
    # cx-openai-5 / cc-deepseek-9 at 22bb19504: quoted and JSON forms passed through, and access_token= had no \b.
    for leaked in ('api_key="SYNTH"', '{"api_key":"SYNTH"}', "GET /x?access_token=SYNTH failed"):
        assert "SYNTH" not in (M.redact_secrets(leaked) or ""), leaked
    # ...and the newest REAL failure wins over a newer skip for the row's own message
    out = M.get_automations(
        query=lambda sql: (
            [wf("1", "w1")]
            if "from workflow_entity" in sql
            else [
                {"raw": ["1", NOW - HOUR, blob("previous execution is still running (within SLA)")]},
                {"raw": ["1", NOW - 2 * HOUR, blob("Assert REQUESTED failed")]},
            ]
            if "from execution_entity e" in sql
            else [ex("1", "error", NOW - 2 * HOUR), ex("1", "error", NOW - HOUR)]
        ),
        now=NOW,
        cron=lambda: [],
        drafts=0,
    )
    assert out["workflows"][0]["last_error_kind"] == "failed"
    assert "REQUESTED" in (out["workflows"][0]["last_error"] or "")


def test_cron_entries_counts_jobs_not_assignments_or_macros():
    """cx-openai-5's F5 at 25b3348e: CRON_TZ=/PATH= lines are environment; @reboot is one job."""
    assert M.cron_entries(None) is None
    assert M.cron_entries(["CRON_TZ=America/New_York", "PATH=/usr/local/bin:/usr/bin"]) == []
    lines = [
        "CRON_TZ=America/New_York",
        "*/15 * * * * cd /x && ./run.sh",
        "@reboot sleep 30 && /usr/bin/true",
        "PATH=/usr/bin",
        "0 9 * * 1-5 /usr/bin/true",
    ]
    assert len(M.cron_entries(lines)) == 3


def test_a_source_that_cannot_be_read_is_null_not_zero():
    """cron unreadable → None in the payload; the page must render 'not read', never 'no cron left'."""
    out = M.summarize(M.workflow_rows([wf("1", "a")]), M.run_stats([], NOW), {}, now=NOW, cron_lines=None, drafts=None)
    assert out["kpi"]["cron_left"] is None and out["kpi"]["fail_rate_pct"] is None


def test_the_cache_asks_the_database_once_per_ttl_and_never_leaks_its_clock(monkeypatch):
    """The page polls; the database must not be asked on every render. The timestamp stays inside the module."""
    calls = []

    def counted(**kwargs):
        calls.append(1)
        return {"generated_at": "2026-11-05T12:00:00Z", "workflows": [], "n": len(calls)}

    monkeypatch.setattr(M, "get_automations", counted)
    M._CACHE.clear()
    first = M.get_automations_cached(ttl_s=60)
    second = M.get_automations_cached(ttl_s=60)
    assert len(calls) == 1, "a hit inside the TTL must not reach the source"
    assert first == second
    assert "_at" not in second and "_at" not in first, "the monotonic stamp is internal"
    # an expired entry asks again, and the fresh payload is what comes back
    M._CACHE["payload"]["_at"] -= 61
    third = M.get_automations_cached(ttl_s=60)
    assert len(calls) == 2 and third["n"] == 2
    M._CACHE.clear()


def test_the_route_serves_the_projection_and_refuses_writes(monkeypatch):
    """FQ-130 native helper: /api/v2/n8n/automations is read-only, serves the projection, and never reads as empty."""
    import api_v2
    import lib.data_broker.n8n_automations as real

    payload = {"generated_at": "2026-11-05T12:00:00Z", "workflows": [{"name": "x"}], "kpi": {"runs": 3}}
    monkeypatch.setattr(real, "get_automations_cached", lambda: payload)

    status, body = api_v2.handle("/api/v2/n8n/automations", method="GET", body=None, query={})
    assert status == 200 and body["ok"] is True and body["data"] == payload

    status, body = api_v2.handle("/api/v2/n8n/automations", method="POST", body={}, query={})
    assert status == 405 and body["error"] == "read_only"

    def boom():
        raise RuntimeError("n8n db unreachable")

    monkeypatch.setattr(real, "get_automations_cached", boom)
    status, body = api_v2.handle("/api/v2/n8n/automations", method="GET", body=None, query={})
    assert status == 500 and body["error"] == "RuntimeError" and "n8n db unreachable" in body["detail"]


def test_a_produced_payload_carries_the_row_fields_the_page_reads():
    """cx-openai-3's F4 at a1aa3bd3a: the producer emitted id/area/created/updated while the page reads
    workflow_id/folder/last_run_at, so Area and Last run were permanently em dashes and the seam test passed on a
    schema string. This drives the REAL producer output and asserts the fields the page consumes are present."""
    from datetime import timedelta as _td

    wf = M.workflow_rows([{"raw": ["wf-1", "Nightly job", "t", "[]", "2026-01-01", "2026-11-01", "f", "Risk"]}])[0]
    rows = [ex("wf-1", "success", NOW - _td(hours=4), NOW - _td(hours=4)), ex("wf-1", "error", NOW - _td(hours=1))]
    out = M.summarize([wf], M.run_stats(rows, NOW), {}, now=NOW, cron_lines=[], drafts=0)
    row = out["workflows"][0]
    assert row["workflow_id"] == "wf-1"
    assert row["folder"] == "Risk"
    assert isinstance(row["last_run_at"], str) and row["last_run_at"].startswith(str(NOW.year))
    assert row["last_run_at"] > (NOW - _td(hours=2)).isoformat()  # the newest execution, not the oldest


@pytest.mark.parametrize(
    "key",
    ["API_KEY", "Api_Key", "ACCESS_TOKEN", "Refresh_Token", "ID_TOKEN", "AUTH_TOKEN", "PASSWORD", "CLIENT_SECRET"],
)
@pytest.mark.parametrize("boundary", ["producer", "route"])
def test_mixed_case_structured_secrets_are_absent_at_producer_and_full_route(key, boundary, monkeypatch):
    """Recognizable JSON keys have the same privacy contract regardless of their casing."""
    marker = "synthetic privacy marker"
    message = "Request failed: " + json.dumps({key: marker})
    if boundary == "producer":
        scrubbed = M.parse_error(blob(message))
        assert marker not in scrubbed and "[redacted]" in scrubbed
        assert "Request failed" in scrubbed and M.classify(scrubbed) == "failed"
        assert M.redact_secrets(scrubbed) == scrubbed
        return

    import api_v2
    import lib.data_broker.n8n_automations as routed

    def unavailable():
        raise RuntimeError(message)

    monkeypatch.setattr(routed, "get_automations_cached", unavailable)
    status, result = api_v2.handle("/api/v2/n8n/automations", method="GET", body=None, query={})
    assert status == 500 and result["error"] == "RuntimeError"
    assert marker not in json.dumps(result) and "Request failed" in result["detail"]


@pytest.mark.parametrize("count", [1, 60, 61, 120, 121])
def test_error_classification_covers_workflows_beyond_first_batch(count):
    """The SQL-aware source returns only requested IDs: a later readable skip is never a failure."""
    ids = [f"synthetic-{i:03d}" for i in range(count)]
    started = NOW - HOUR
    requested = []

    def query(sql):
        if "from workflow_entity" in sql:
            return [wf(wid, f"Workflow {i}") for i, wid in enumerate(ids)]
        if "join execution_data" in sql:
            clause = re.search(r"\bin \((.*?)\)", sql)
            assert clause is not None
            batch = [item.replace("''", "'") for item in re.findall(r"'((?:[^']|'')*)'", clause.group(1))]
            assert batch and len(batch) <= 60, "classification queries must remain bounded"
            requested.extend(batch)
            return [
                {"raw": [wid, str(started), blob("previous execution is still running (within SLA)")]}
                for wid in batch
                if wid in ids
            ]
        return [ex(wid, "error", started) for wid in ids]

    out = M.get_automations(query=query, now=NOW, cron=lambda: [], drafts=0)
    assert out["kpi"]["failed"] == 0 and out["kpi"]["skipped"] == count
    assert out["counts"]["failing"] == 0
    assert len(out["workflows"]) == count
    assert all(row["fail"] == 0 and row["skipped"] == 1 for row in out["workflows"])
    assert len(requested) == len(set(requested)) == count and set(requested) == set(ids)
