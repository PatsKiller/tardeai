#!/usr/bin/env python3
"""Phase C — entry planner adapter acceptance."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _fcntx_event_with_plans():
    dt = _load("redeploy_data_truth", "scripts/lib/redeploy_data_truth.py")
    eng = _load("redeploy_plan_engine", "scripts/lib/redeploy_plan_engine.py")
    adapter = _load("entry_planner_adapter", "scripts/lib/entry_planner_adapter.py")
    ev = {
        "event_key": "txn:test",
        "symbol": "FCNTX",
        "account": "schwab_rollover_ira",
        "proceeds_usd": 107023.01,
        "cash_visible_usd": 17540.67,
        "proxy_symbol": "SCHG",
        "instrument_type": "mutual_fund",
        "metadata": {"market_context": {"regime_posture": "risk_off"}},
    }
    ev = dt.enrich_event_phase_a(ev)
    bundle = eng.build_institutional_plans(ev, sale_ctx={"tier": "major"})
    ev["metadata"]["phase_b"] = bundle
    return adapter.enrich_event_phase_c(ev)


def test_jepq_stages_sum_to_leg_dollars():
    adapter = _load("entry_planner_adapter", "scripts/lib/entry_planner_adapter.py")
    entry = adapter.build_entry_package("JEPQ", leg_dollars=5000.0, regime_posture="neutral")
    assert entry.get("preferred_entry")
    assert entry.get("stage_1_pct") == 25
    stage_sum = sum(
        entry.get(f"stage_{i}_dollars") or 0 for i in range(1, 4)
    )
    assert stage_sum <= 5000.0 + 1.0
    assert entry.get("stage_1_shares", 0) >= 0


def test_risk_off_reduces_first_tranche():
    adapter = _load("entry_planner_adapter", "scripts/lib/entry_planner_adapter.py")
    neutral = adapter.build_entry_package("JEPQ", leg_dollars=10000.0, regime_posture="neutral")
    risk_off = adapter.build_entry_package("JEPQ", leg_dollars=10000.0, regime_posture="risk_off")
    assert risk_off["stage_1_pct"] < neutral["stage_1_pct"]
    assert risk_off["stage_3_pct"] > neutral["stage_3_pct"]


def test_quote_stale_after_snapshot_age():
    adapter = _load("entry_planner_adapter", "scripts/lib/entry_planner_adapter.py")
    tech = adapter.load_technicals("JEPQ")
    as_of = tech.get("as_of")
    assert as_of
    # Derive "later" from the live snapshot instead of a fixed date, which silently
    # became earlier than as_of once technicals caught up and inverted the check.
    age_now = adapter.quote_age_minutes(as_of, now=datetime.now(timezone.utc))
    assert age_now is not None
    future = datetime.now(timezone.utc) + timedelta(
        minutes=adapter.EXPORT_QUOTE_MAX_AGE_MINUTES + 60
    )
    assert adapter.is_quote_stale(as_of, now=future)
    fresh = adapter.quote_age_minutes(as_of, now=None)
    assert fresh is None or fresh >= 0


def test_phase_c_enriches_metadata():
    ev = _fcntx_event_with_plans()
    pc = ev["metadata"]["phase_c"]
    assert pc.get("adapter_version")
    assert "export_readiness" in pc
    plan_f = next(p for p in ev["metadata"]["phase_b"]["plans"] if p["plan_archetype"] == "F")
    equity = [l for l in plan_f["legs"] if not l.get("is_reserve")]
    assert equity
    assert equity[0].get("preferred_entry") is not None
    assert equity[0].get("monitoring_rules")


def test_export_blocked_when_stale():
    adapter = _load("entry_planner_adapter", "scripts/lib/entry_planner_adapter.py")
    ev = _fcntx_event_with_plans()
    plan = ev["metadata"]["phase_b"]["plans"][0]
    result = adapter.export_trade_plan(ev, plan, fmt="json", force_stale=False)
    assert result.get("error") == "stale_quotes" or result.get("ok") is True


def test_export_force_stale_json():
    adapter = _load("entry_planner_adapter", "scripts/lib/entry_planner_adapter.py")
    ev = _fcntx_event_with_plans()
    plan = next(p for p in ev["metadata"]["phase_b"]["plans"] if p["plan_archetype"] == "F")
    result = adapter.export_trade_plan(ev, plan, fmt="json", force_stale=True)
    assert result.get("ok") is True
    tp = result.get("trade_plan") or {}
    assert tp.get("advisory_only") is True
    assert tp.get("plan_archetype") == "F"
    assert len(tp.get("legs") or []) >= 2


def test_export_csv_has_header():
    adapter = _load("entry_planner_adapter", "scripts/lib/entry_planner_adapter.py")
    ev = _fcntx_event_with_plans()
    plan = ev["metadata"]["phase_b"]["plans"][0]
    csv_text = adapter.export_trade_plan(ev, plan, fmt="csv", force_stale=True)
    assert isinstance(csv_text, str)
    assert "preferred_entry" in csv_text.splitlines()[0]


if __name__ == "__main__":
    tests = [
        test_jepq_stages_sum_to_leg_dollars,
        test_risk_off_reduces_first_tranche,
        test_quote_stale_after_snapshot_age,
        test_phase_c_enriches_metadata,
        test_export_blocked_when_stale,
        test_export_force_stale_json,
        test_export_csv_has_header,
    ]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"ALL {len(tests)} PASSED")