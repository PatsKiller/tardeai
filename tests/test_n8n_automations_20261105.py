"""Hermetic tests for the Automations projection (design automations/v001, APPROVED).

No database, no docker, no crontab: every source is handed in. The live numbers were checked by hand against the n8n DB
when the module was written (33 non-archived workflows, 2,988 runs / 2,920 failed in 7 days, 368 cron lines).
"""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("n8n_automations", ROOT / "scripts/lib/data_broker/n8n_automations.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def blob(message=None):
    """n8n's flattened execution_data: [{key: index}, …, values…], the error nested behind two indices."""
    flat = [{}, {}, {"error": "5", "runData": "6"}, {}, {}, {"message": "17", "level": "14"}, {}, {}, {}, {}, {}, {}, {}, {}, "error", {}, {}, message]
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
    stats = M.run_stats([ex("1", "error", NOW - HOUR, NOW - HOUR + timedelta(seconds=2)),
                         ex("1", "error", NOW - 2 * HOUR),
                         ex("2", "success", NOW - HOUR, NOW - HOUR + timedelta(seconds=4))], NOW)
    out = M.summarize(workflows, stats, {"1": {"kind": "relay_refused", "one_line": "relay 403"}},
                      now=NOW, cron_lines=["a", "b"], drafts=1)
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
    rows = ([ex("1", "success", NOW - 3 * HOUR)] * 50 +
            [ex("1", "error", NOW - 2 * HOUR)] * 2)
    stats = M.run_stats(rows, NOW)
    out = M.summarize(wfs, stats, {}, now=NOW, cron_lines=[], drafts=0)
    assert out["kpi"]["ok"] == 50 and out["kpi"]["failed"] == 2       # the counts are real
    assert out["kpi"]["fail_rate_pct"] is None                        # the ratio is not
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
    for sql in ("select 1; drop table workflow_entity",
                "select 1; drop table workflow_entity;",
                "select 1;;delete from workflow_entity",
                "select 'a;b'"):
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
