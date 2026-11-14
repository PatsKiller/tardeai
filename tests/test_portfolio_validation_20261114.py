"""PR-004 / PR-005 — portfolio validation projections (PortfolioGates@v1, PortfolioChanges@v1).

Hermetic: no database, no filesystem, no network. Rows are synthetic dicts shaped like the served columns.
Every test pins a rule from the operator's rails — an empty scope is UNKNOWN and never PASS, a NULL
``blocks_trading`` is unknown and never "no", a store that cannot be read is UNKNOWN and not "nothing happened",
and a closed gate's timestamp is a closure time and never a live heartbeat.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from lib import portfolio_validation as PV  # noqa: E402

NOW = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)


def gate(**over) -> dict:
    row = {
        "gate_id": "VG-PORT-STOP-COVERAGE", "title": "Order protection", "category": "Order protection",
        "source": "declaration", "status": "PASSED", "blocks": "Order protection", "blocks_trading": True,
        "due_at": None, "owner": "risk", "fix_ref": None, "label": "FIXED_UNPROVEN",
        "proof_window_end": NOW + timedelta(days=3), "proven_at": NOW - timedelta(hours=22),
        "last_eval_result": "PASS", "last_evaluated_at": NOW - timedelta(hours=22),
        "last_eval_detail": {"detail": "12 positions, 12 protected"}, "evidence": [{"k": "v"}],
        "decl_path": "config/validation_windows/order_protection/stop_coverage.json",
    }
    row.update(over)
    return row


def fresh(rows, *, computed=None) -> dict:
    times = [r["last_evaluated_at"] for r in rows if r.get("last_evaluated_at")]
    return {"computed_at": computed if computed is not None else (max(times) if times else None), "n": len(rows)}


def gates(rows, *a, **kw):
    return PV.gates_model(rows, fresh(rows) if rows is not None else None, now=NOW, *a, **kw)


# ---- PR-004 gates: absence is never PASS ---------------------------------------------------------------

def test_unreadable_store_is_unknown_with_its_reason_and_no_counts():
    m = PV.gates_model(None, None, now=NOW)
    assert m["schema"] == PV.GATES_SCHEMA
    assert m["state"] == "UNKNOWN"
    assert m["reason"] == "gate store unreadable"
    assert m["counts"] is None and m["items"] == [] and m["snapshot"] is None
    assert m["scope"]["gates"] is None and m["scope"]["categories"] == ["Order protection"]
    assert m["writer"]["lane_id"] == "validation-gates-sync"


def test_rows_read_but_fresh_count_unreadable_is_unknown():
    m = PV.gates_model([gate()], None, now=NOW)
    assert m["state"] == "UNKNOWN" and m["reason"] == "gate store unreadable"


def test_empty_scope_is_unknown_never_pass_with_measured_zero_counts():
    m = gates([])
    assert m["state"] == "UNKNOWN"
    assert m["text"] == "not declared"
    assert "no portfolio gate is declared" in m["reason"]
    assert m["counts"] == {"rows": 0, "failed": 0, "overdue": 0, "open": 0, "closed": 0,
                           "blocks_trading": 0, "blocks_trading_unknown": 0, "never_evaluated": 0}
    assert m["items"] == []
    assert "PASS" not in m["state"]


def test_gates_exist_but_none_evaluated_is_unknown():
    m = gates([gate(status="OPEN", last_evaluated_at=None, last_eval_result=None)])
    assert m["state"] == "UNKNOWN" and "none has ever been evaluated" in m["reason"]


def test_an_open_gate_never_evaluated_is_unknown_not_stale():
    rows = [gate(), gate(gate_id="VG-2", status="OPEN", last_eval_result=None, last_evaluated_at=None)]
    m = gates(rows)
    assert m["state"] == "UNKNOWN"
    assert "1 open gate(s) have no recorded evaluation" == m["reason"]
    assert m["counts"]["never_evaluated"] == 1 and m["counts"]["open"] == 1


# ---- PR-004 gates: a closed gate is closed, not stale --------------------------------------------------

def test_a_scope_of_closed_gates_is_ok_with_the_closure_age_named_never_stale():
    """The live shape: five PASSED gates, newest evaluation ~22 h old. That is a closure time, not a dead lane."""
    rows = [gate(gate_id=f"VG-R3-{n}") for n in ("A", "B", "C")]
    m = gates(rows)
    assert m["state"] == "OK"
    assert m["snapshot"]["basis"] == "closed_gates"
    assert m["snapshot"]["age_s"] == 22 * 3600
    assert "all closed" in m["text"] and "22.0 h" in m["text"]
    assert all(i["clock"]["state"] == "closed" for i in m["items"])
    assert m["items"][0]["clock"]["text"] == "closed at its last evaluation (22.0 h ago)"


def test_an_open_gate_older_than_the_threshold_makes_the_scope_stale():
    rows = [gate(), gate(gate_id="VG-2", status="OPEN", last_evaluated_at=NOW - timedelta(hours=2),
                         last_eval_result=None)]
    m = gates(rows)
    assert m["state"] == "STALE"
    assert m["snapshot"]["basis"] == "open_gates" and m["snapshot"]["oldest_open_age_s"] == 7200
    assert "7200s old > 900s" in m["reason"]


def test_a_freshly_evaluated_open_gate_is_ok():
    rows = [gate(), gate(gate_id="VG-2", status="OPEN", last_evaluated_at=NOW - timedelta(minutes=1),
                         last_eval_result=None)]
    m = gates(rows)
    assert m["state"] == "OK"
    assert m["items"][1]["clock"]["state"] == "ok"


def test_an_open_gate_clock_in_the_future_is_unknown():
    rows = [gate(status="OPEN", last_evaluated_at=NOW + timedelta(hours=1))]
    m = gates(rows)
    assert m["state"] == "UNKNOWN" and "future" in m["reason"]
    assert m["items"][0]["clock"]["state"] == "future"


# ---- PR-004 gates: the tri-state is preserved ----------------------------------------------------------

def test_blocks_trading_null_is_unknown_and_is_not_counted_as_no():
    rows = [gate(gate_id="VG-T", blocks_trading=True), gate(gate_id="VG-F", blocks_trading=False),
            gate(gate_id="VG-N", blocks_trading=None)]
    m = gates(rows)
    by = {i["gate_id"]: i for i in m["items"]}
    assert by["VG-T"]["blocks_trading"] is True
    assert by["VG-F"]["blocks_trading"] is False
    assert by["VG-N"]["blocks_trading"] is None
    assert m["counts"]["blocks_trading"] == 1        # only a declared True
    assert m["counts"]["blocks_trading_unknown"] == 1  # not folded into False


def test_a_failed_gate_counts_as_failed_by_status_or_by_result():
    rows = [gate(gate_id="VG-1", status="FAILED", last_eval_result="PASS"),
            gate(gate_id="VG-2", status="OPEN", last_eval_result="FAIL",
                 last_evaluated_at=NOW - timedelta(minutes=2))]
    m = gates(rows)
    assert m["counts"]["failed"] == 2
    assert "failed at its last evaluation" in {i["gate_id"]: i for i in m["items"]}["VG-2"]["next_action"]


# ---- PR-004 gates: item shape --------------------------------------------------------------------------

def test_every_row_carries_its_status_clock_owner_next_action_and_window():
    m = gates([gate()])
    it = m["items"][0]
    assert it["status"] == "PASSED"
    assert it["last_eval"] == {"result": "PASS", "at": (NOW - timedelta(hours=22)).isoformat(),
                               "detail": "12 positions, 12 protected"}
    assert it["clock"]["at"] == (NOW - timedelta(hours=22)).isoformat()
    assert it["owner"] == "risk"
    assert it["label_text"] == "FIXED · UNPROVEN OVER TIME"
    assert it["window"]["end"] == (NOW + timedelta(days=3)).isoformat()
    assert it["window"]["days_remaining"] == 3.0
    assert "proving over the window to" in it["next_action"]
    assert it["evidence"] == [{"k": "v"}]
    assert it["decl_path"].endswith("stop_coverage.json")


def test_a_proof_window_that_lapsed_unproven_is_not_reported_as_no_action():
    # The live shape: PASSED, label FIXED_UNPROVEN, proven_at NULL, its 24 h proof window ended.
    it = gates([gate(label="FIXED_UNPROVEN", proven_at=None, proof_window_end=NOW - timedelta(hours=1),
                     last_evaluated_at=NOW - timedelta(hours=25))])["items"][0]
    assert it["window"]["proven_at"] is None
    assert "proof window ended 2026-11-14" in it["next_action"]
    assert "no proven verdict recorded" in it["next_action"]
    assert "FIXED · UNPROVEN OVER TIME" in it["next_action"]
    assert "No action unless it regresses" not in it["next_action"]


def test_a_proof_window_still_running_keeps_the_proving_sentence():
    it = gates([gate(label="FIXED_UNPROVEN", proven_at=None,
                     proof_window_end=NOW + timedelta(hours=6))])["items"][0]
    assert it["next_action"] == "No action unless it regresses: proving over the window to 2026-11-14"


def test_an_elapsed_window_with_a_recorded_verdict_is_not_called_unproven():
    # proven_at recorded: the verdict exists, so the sentence must not claim it is missing.
    it = gates([gate(label="FIXED_UNPROVEN", proven_at=NOW - timedelta(hours=2),
                     proof_window_end=NOW - timedelta(hours=1))])["items"][0]
    assert it["window"]["proven_at"] == (NOW - timedelta(hours=2)).isoformat()
    assert "no proven verdict" not in it["next_action"]


def test_an_unlabelled_gate_has_no_label_text_and_a_stated_next_action():
    it = gates([gate(label=None, status="WAIVED")])["items"][0]
    assert it["label_text"] is None
    assert it["next_action"].startswith("risk: review the gate; it is waived")


def test_the_writer_receipt_time_is_published_verbatim():
    m = PV.gates_model([gate()], fresh([gate()]), now=NOW, receipt_ok_at=NOW - timedelta(minutes=3))
    assert m["writer"]["last_ok_at"] == (NOW - timedelta(minutes=3)).isoformat()
    assert m["writer"]["receipt"] == "data/runtime/validation-gates-sync_last.json"


def test_a_naive_timestamp_is_refused_rather_than_assumed_utc():
    m = gates([gate(last_evaluated_at="2026-11-14 14:00:00")])
    assert m["state"] == "UNKNOWN" and m["text"] == "clock unreadable"
    assert m["items"][0]["clock"]["state"] == "unreadable" and m["items"][0]["last_eval"]["at"] is None
    assert m["counts"]["clock_unreadable"] == 1


# ---- PR-005 changes: the visit window ----------------------------------------------------------------

def ev(**over) -> dict:
    row = {"event_id": 41, "source_kind": "gate", "source_id": "VG-PORT-STOP-COVERAGE",
           "category": "Order protection", "transition": "passed", "label": "FIXED_UNPROVEN",
           "proof_window_end": NOW + timedelta(days=3), "occurred_at": NOW - timedelta(hours=1),
           "detected_at": NOW - timedelta(hours=1) + timedelta(seconds=4),
           "summary": "stop coverage passed", "owner": "risk", "evidence": {"n": 12}}
    row.update(over)
    return row


def test_changes_since_the_visit_cursor_preserve_each_events_own_timestamp():
    since = NOW - timedelta(hours=6)
    m = PV.changes_model([ev(), ev(event_id=40, occurred_at=NOW - timedelta(hours=5))], now=NOW, since=since)
    assert m["schema"] == PV.CHANGES_SCHEMA and m["state"] == "OK"
    assert m["window"] == {"basis": "last_visit", "since": since.isoformat(), "until": NOW.isoformat()}
    assert [i["event_id"] for i in m["items"]] == [41, 40]
    assert m["items"][1]["occurred_at"] == (NOW - timedelta(hours=5)).isoformat()
    assert m["items"][0]["detected_at"] == (NOW - timedelta(hours=1, seconds=-4)).isoformat()
    assert m["count"] == 2 and m["latest_at"] == (NOW - timedelta(hours=1)).isoformat()


def test_no_visit_cursor_falls_back_to_24h_and_says_so():
    m = PV.changes_model([], now=NOW, since=None)
    assert m["state"] == "OK" and m["count"] == 0
    assert m["window"]["basis"] == "fallback_24h"
    assert m["window"]["since"] == (NOW - timedelta(hours=24)).isoformat()


def test_an_unreadable_change_store_is_unknown_not_an_empty_list():
    m = PV.changes_model(None, now=NOW, since=NOW - timedelta(hours=6))
    assert m["state"] == "UNKNOWN" and m["reason"] == "change store unreadable"
    assert m["count"] is None
    assert m["window"]["since"] == (NOW - timedelta(hours=6)).isoformat()


def test_a_future_visit_cursor_is_unknown_not_an_empty_list():
    m = PV.changes_model([], now=NOW, since=NOW + timedelta(hours=2))
    assert m["state"] == "UNKNOWN" and "future" in m["reason"] and m["count"] is None


def test_a_full_page_names_that_the_window_may_be_truncated():
    rows = [ev(event_id=i, occurred_at=NOW - timedelta(minutes=i + 1)) for i in range(3)]
    m = PV.changes_model(rows, now=NOW, since=NOW - timedelta(hours=1), limit=3)
    assert m["may_be_truncated"] is True
    assert PV.changes_model(rows[:2], now=NOW, since=NOW - timedelta(hours=1), limit=3)["may_be_truncated"] is False


def test_an_event_outside_the_visit_window_is_counted_not_published():
    """A wiring mistake must not show yesterday's change as 'since your visit'; the exclusion is measured."""
    since = NOW - timedelta(hours=6)
    rows = [ev(event_id=1, occurred_at=NOW - timedelta(hours=24)),   # before the visit
            ev(event_id=2, occurred_at=NOW - timedelta(hours=1)),    # inside
            ev(event_id=3, occurred_at=NOW + timedelta(hours=1))]    # future clock fault
    m = PV.changes_model(rows, now=NOW, since=since)
    assert [i["event_id"] for i in m["items"]] == [2]
    assert m["count"] == 1
    assert m["outside_window"] == {"before": 1, "after": 1, "unreadable": 0, "out_of_scope": 0}


def test_another_pages_event_is_not_published_as_a_portfolio_change():
    """Live 2026-11-14: validation_events carries Scheduler health / Data freshness rows too. The portfolio page
    shows its own scope; a leak is counted (out_of_scope) instead of rendered."""
    since = NOW - timedelta(hours=6)
    rows = [ev(event_id=1),
            ev(event_id=2, category="Scheduler health", source_id="VG-R3-VALIDATION-SYNC-ALIVE"),
            ev(event_id=3, category="Data freshness", source_id="VG-R3-AMANX-QUOTE-FRESH")]
    m = PV.changes_model(rows, now=NOW, since=since)
    assert [i["event_id"] for i in m["items"]] == [1]
    assert m["count"] == 1
    assert m["outside_window"]["out_of_scope"] == 2


def test_the_live_shape_a_window_that_starts_after_the_last_event_is_a_measured_zero():
    """Live on 2026-11-14: the newest Order-protection event is 2026-11-13T15:04Z, so a fresh visit has none."""
    m = PV.changes_model([ev(event_id=1, occurred_at=NOW - timedelta(hours=24))], now=NOW,
                         since=NOW - timedelta(minutes=1))
    assert m["state"] == "OK" and m["count"] == 0 and m["items"] == []
    assert m["outside_window"]["before"] == 1


# ---- handler glue: one read path, params are scope/limit only ------------------------------------------

def test_read_gates_issues_the_scoped_sql_and_never_writes():
    calls = []

    def q(sql, params=None, fetch="all"):
        calls.append((sql, params, fetch))
        return [gate()] if fetch == "all" else fresh([gate()])

    m = PV.read_gates(q, now=NOW, receipt_ok_at=lambda lane: NOW - timedelta(minutes=3))
    assert m["state"] == "OK"
    assert [c[2] for c in calls] == ["all", "one"]
    assert all(c[1] == (["Order protection"],) for c in calls)
    assert all("validation_gates" in c[0] and "INSERT" not in c[0].upper() and "UPDATE" not in c[0].upper()
               for c in calls)


def test_read_changes_windows_the_events_and_keeps_the_cursor_basis():
    calls = []

    def q(sql, params=None, fetch="all"):
        calls.append((sql, params, fetch))
        return [ev()]

    since = NOW - timedelta(hours=6)
    m = PV.read_changes(q, since=since, now=NOW)
    assert m["state"] == "OK" and m["window"]["basis"] == "last_visit"
    sql, params, fetch = calls[0]
    assert "validation_events" in sql and "category = ANY" in sql
    assert params[0] == ["Order protection"]
    assert params[1] == since.isoformat() and params[2] == NOW.isoformat()
    assert params[3] == PV.EVENT_LIMIT and fetch == "all"


def test_read_changes_still_windows_the_query_when_the_cursor_is_missing():
    seen = {}

    def q(sql, params=None, fetch="all"):
        seen["params"] = params
        return []

    PV.read_changes(q, since=None, now=NOW)
    assert seen["params"][1] == (NOW - timedelta(hours=24)).isoformat()


def test_a_present_but_unreadable_cursor_is_unknown_not_the_24h_fallback():
    """`since=banana` must not silently become 'the last 24 h': the operator would be told a window they are not in."""
    calls = []

    def q(sql, params=None, fetch="all"):
        calls.append((sql, params, fetch))
        return []

    m = PV.read_changes(q, since=None, now=NOW, cursor_raw="not-a-timestamp")
    assert m["state"] == "UNKNOWN"
    assert m["reason"] == "the visit cursor is not a readable UTC timestamp"
    assert m["window"]["basis"] == "unreadable_cursor"
    assert m["count"] is None and m["items"] == []
    assert calls == []   # no read is issued against a window we cannot name


# ---- producer readiness (lead item c): the lane is ready for a NEW portfolio declaration ---------------------
# Run against the sync lane's own sqlite stand-in (built from the real migrations), not the live store. This is the
# evidence behind the 22 h `last_evaluated_at` in the live rows: a CLOSED gate is never re-evaluated, while an OPEN
# one advances its clock on every 5-minute pass. A new portfolio-category declaration is ingested and evaluated in
# that same pass.
from validation_gates_sync import run as sync_run  # noqa: E402
from vg_fixtures_20261112 import NOW as VG_NOW, Conn, decl  # noqa: E402

QUERIES = {"q_zero": {"sql": "SELECT 0 AS value"}, "q_five": {"sql": "SELECT 5 AS value"}}


def _inbox(tmp_path, *docs):
    d = tmp_path / "data" / "coordination" / "validation_gates" / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    for i, doc in enumerate(docs):
        (d / f"{i:02d}.json").write_text(__import__("json").dumps(doc), encoding="utf-8")
    return d


def test_a_new_portfolio_declaration_is_evaluated_by_the_next_lane_pass(tmp_path):
    c = Conn()
    _inbox(tmp_path, decl("VG-PORT-COUNT-AGREES", check_kind="sql_threshold",
                          check_spec={"query_id": "q_zero", "op": "<=", "value": 0}))
    out = sync_run(c, root=tmp_path, queries=QUERIES, now=VG_NOW, apply=True, run_id="t:1", postgres=False)
    assert out["ingested"] == 1 and out["refused"] == 0
    row = c.q("SELECT gate_id, category, status, last_eval_result, last_evaluated_at FROM validation_gates")
    assert len(row) == 1
    gid, cat, status, result, at = row[0]
    assert (gid, cat, status, result) == ("VG-PORT-COUNT-AGREES", "Order protection", "PASSED", "PASS")
    assert at is not None and "2026-11-12" in str(at)


def test_an_open_gate_clock_advances_every_pass_which_is_why_a_closed_one_freezes(tmp_path):
    c = Conn()
    _inbox(tmp_path, decl("VG-PORT-OPEN", check_kind="sql_threshold",
                          check_spec={"query_id": "q_five", "op": "<=", "value": 0}))
    from datetime import timedelta
    sync_run(c, root=tmp_path, queries=QUERIES, now=VG_NOW, apply=True, run_id="t:1", postgres=False)
    first = c.q("SELECT status, last_evaluated_at FROM validation_gates")[0]
    assert first[0] == "OPEN"
    sync_run(c, root=tmp_path, queries=QUERIES, now=VG_NOW + timedelta(minutes=5), apply=True, run_id="t:2",
             postgres=False)
    second = c.q("SELECT status, last_evaluated_at FROM validation_gates")[0]
    assert second[0] == "OPEN"
    assert second[1] > first[1]   # the clock moves on every pass while the gate is open
