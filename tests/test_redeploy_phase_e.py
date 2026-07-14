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


def test_idempotent_record_fill():
    mon = _load("redeploy_monitor", "scripts/lib/redeploy_monitor.py")
    try:
        from db_adapter import get_connection
    except Exception:
        return  # skip if no DB
    conn = get_connection()
    cur = conn.cursor()
    mon.ensure_monitor_tables(cur)
    conn.commit()

    idem = f"test-{uuid.uuid4().hex[:16]}"
    body = {
        "ticker": "JEPQ",
        "stage": 1,
        "filled_shares": 18,
        "filled_price": 60.12,
        "account": "schwab_rollover_ira",
        "plan_archetype": "F",
        "idempotency_key": idem,
        "evidence_note": "phase_e test fixture",
    }
    r1 = mon.record_stage_fill(cur, 144, body)
    conn.commit()
    assert r1.get("ok"), r1
    r2 = mon.record_stage_fill(cur, 144, body)
    assert r2.get("duplicate") is True
    assert r2.get("fill_id") == r1.get("fill", {}).get("id")

    state = mon.get_monitoring_state(cur, 144)
    assert state.get("ok")
    assert state.get("fill_summary", {}).get("fill_count", 0) >= 1


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
        test_idempotent_record_fill,
    ]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"ALL {len(tests)} PASSED")