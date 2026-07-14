#!/usr/bin/env python3
"""Phase E — redeploy monitoring acceptance."""
from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _fcntx_event():
    dt = _load("redeploy_data_truth", "scripts/lib/redeploy_data_truth.py")
    ev = {
        "event_key": "txn:test",
        "symbol": "FCNTX",
        "account": "schwab_rollover_ira",
        "proceeds_usd": 107023.01,
        "cash_visible_usd": 17540.67,
        "proxy_symbol": "SCHG",
        "instrument_type": "mutual_fund",
        "metadata": {},
    }
    return dt.enrich_event_phase_a(ev)


def test_restoration_metrics_empty_fills():
    mon = _load("redeploy_monitor", "scripts/lib/redeploy_monitor.py")
    ev = _fcntx_event()
    m = mon.compute_restoration_metrics(ev, [], plan_archetype="F")
    assert m["total_removed_usd"] > 0
    assert m["restoration_pct"] == 0.0
    assert len(m["sectors"]) >= 5


def test_restoration_metrics_with_jepq_fill():
    mon = _load("redeploy_monitor", "scripts/lib/redeploy_monitor.py")
    ev = _fcntx_event()
    fills = [{
        "ticker": "JEPQ",
        "filled_dollars": 4385.0,
        "plan_archetype": "F",
        "stage": 1,
    }]
    m = mon.compute_restoration_metrics(ev, fills, plan_archetype="F")
    assert m["total_restored_usd"] == 4385.0
    assert m["restoration_pct"] > 0


def test_fill_summary_aggregates_stages():
    mon = _load("redeploy_monitor", "scripts/lib/redeploy_monitor.py")
    fills = [
        {"ticker": "JEPQ", "stage": 1, "filled_shares": 18, "filled_dollars": 1096.0},
        {"ticker": "JEPQ", "stage": 2, "filled_shares": 18, "filled_dollars": 1096.0},
    ]
    s = mon.build_fill_summary(fills)
    assert s["fill_count"] == 2
    assert s["tickers"][0]["ticker"] == "JEPQ"
    assert s["total_dollars_deployed"] == 2192.0


def _db_cursor(mon):
    """Open a DB transaction for guard tests. Every test using this MUST roll back —
    the 2026-07-13 P0 pollution came from a test in this file committing real fills."""
    try:
        from db_adapter import get_connection
    except Exception:
        return None, None
    conn = get_connection()
    cur = conn.cursor()
    mon.ensure_monitor_tables(cur)
    # Neutralize the JSON outcome-bus side effect — it is a file write and would
    # survive a DB rollback.
    mon.append_outcome_bus = lambda *a, **k: None
    return conn, cur


def _pick_open_event(cur):
    cur.execute("SELECT id FROM deploy_events ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    return int(row[0]) if row else None


def test_fixture_note_rejected_in_production():
    mon = _load("redeploy_monitor", "scripts/lib/redeploy_monitor.py")
    conn, cur = _db_cursor(mon)
    if not conn:
        return  # skip if no DB
    try:
        r = mon.record_stage_fill(cur, 1, {
            "ticker": "JEPQ", "stage": 1, "filled_shares": 18, "filled_price": 60.12,
            "account": "schwab_rollover_ira",
            "evidence_note": "phase_e test fixture",
        })
        assert not r.get("ok")
        assert "fixture_marker_rejected" in str(r.get("error"))
    finally:
        conn.rollback()


def test_test_environment_requires_optin():
    import os
    mon = _load("redeploy_monitor", "scripts/lib/redeploy_monitor.py")
    conn, cur = _db_cursor(mon)
    if not conn:
        return
    os.environ.pop("REDEPLOY_ALLOW_TEST_FILLS", None)
    try:
        r = mon.record_stage_fill(cur, 1, {
            "ticker": "JEPQ", "stage": 1, "filled_shares": 18, "filled_price": 60.12,
            "account": "schwab_rollover_ira", "environment": "test",
        })
        assert not r.get("ok")
        assert "test_fills_forbidden" in str(r.get("error"))
    finally:
        conn.rollback()


def test_test_fill_quarantined_from_metrics():
    import os
    mon = _load("redeploy_monitor", "scripts/lib/redeploy_monitor.py")
    conn, cur = _db_cursor(mon)
    if not conn:
        return
    eid = _pick_open_event(cur)
    if not eid:
        conn.rollback()
        return
    os.environ["REDEPLOY_ALLOW_TEST_FILLS"] = "1"
    try:
        before = mon.get_monitoring_state(cur, eid).get("fill_summary", {}).get("fill_count", 0)
        r = mon.record_stage_fill(cur, eid, {
            "ticker": "JEPQ", "stage": 1, "filled_shares": 7, "filled_price": 61.01,
            "account": "schwab_rollover_ira", "environment": "test",
            "idempotency_key": f"guard-{uuid.uuid4().hex[:16]}",
        })
        assert r.get("ok"), r
        assert r.get("environment") == "test"
        assert r.get("hermes_outcome_id") is None
        after = mon.get_monitoring_state(cur, eid).get("fill_summary", {}).get("fill_count", 0)
        assert after == before, "test fill leaked into production monitoring metrics"
    finally:
        os.environ.pop("REDEPLOY_ALLOW_TEST_FILLS", None)
        conn.rollback()


def test_duplicate_content_and_idempotency_rejected():
    mon = _load("redeploy_monitor", "scripts/lib/redeploy_monitor.py")
    conn, cur = _db_cursor(mon)
    if not conn:
        return
    eid = _pick_open_event(cur)
    if not eid:
        conn.rollback()
        return
    idem = f"guard-{uuid.uuid4().hex[:16]}"
    body = {
        "ticker": "JEPQ", "stage": 1, "filled_shares": 11, "filled_price": 60.55,
        "account": "schwab_rollover_ira", "plan_archetype": "F",
        "idempotency_key": idem,
        "evidence_note": "operator statement row 4",
    }
    try:
        r1 = mon.record_stage_fill(cur, eid, body)
        assert r1.get("ok"), r1
        # Same idempotency key → duplicate short-circuit
        r2 = mon.record_stage_fill(cur, eid, body)
        assert r2.get("duplicate") is True
        assert r2.get("fill_id") == r1.get("fill", {}).get("id")
        # Same content, different key → content-duplicate rejection
        body3 = dict(body, idempotency_key=f"guard-{uuid.uuid4().hex[:16]}")
        r3 = mon.record_stage_fill(cur, eid, body3)
        assert not r3.get("ok")
        assert r3.get("error") == "duplicate_fill_content"
        # Same content with a distinct broker confirmation → accepted
        body4 = dict(body3, idempotency_key=f"guard-{uuid.uuid4().hex[:16]}",
                     broker_confirmation_id=f"CONF-{uuid.uuid4().hex[:8]}")
        r4 = mon.record_stage_fill(cur, eid, body4)
        assert r4.get("ok"), r4
    finally:
        conn.rollback()


def test_reeval_flags_holdings_stale():
    mon = _load("redeploy_monitor", "scripts/lib/redeploy_monitor.py")
    ev = _fcntx_event()
    ev["sold_at"] = "2026-07-14"
    ev["metadata"]["phase_a"]["reconciliation"]["reconciliation_status"] = "holdings_stale"
    flags = mon._reeval_flags(ev, [])
    codes = {f["code"] for f in flags}
    assert "REEVAL-000" in codes


if __name__ == "__main__":
    tests = [
        test_restoration_metrics_empty_fills,
        test_restoration_metrics_with_jepq_fill,
        test_fill_summary_aggregates_stages,
        test_reeval_flags_holdings_stale,
        test_fixture_note_rejected_in_production,
        test_test_environment_requires_optin,
        test_test_fill_quarantined_from_metrics,
        test_duplicate_content_and_idempotency_rejected,
    ]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"ALL {len(tests)} PASSED")