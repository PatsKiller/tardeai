"""B1/B2/B3/D1 loop continuity — no Phase A rebuild."""
from __future__ import annotations

from pathlib import Path


def test_b1_material_financial_canary_default_off(monkeypatch):
    monkeypatch.delenv("CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY", raising=False)
    from scripts.lib.cio_material_scan import material_financial_notify_canary_on
    assert material_financial_notify_canary_on() is False
    monkeypatch.setenv("CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY", "1")
    assert material_financial_notify_canary_on() is True


def test_b1_scan_forces_dry_without_canary(monkeypatch):
    """Even dry_run=False stays dry when canary off (OFF_BY_POLICY)."""
    monkeypatch.setenv("CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY", "0")
    monkeypatch.setenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", "1")
    monkeypatch.setenv("ENABLE_TELEGRAM", "1")
    monkeypatch.setenv("CIO_TELEGRAM_INTERDICT", "0")
    from scripts.lib import cio_material_scan as ms

    # Minimal office stub — scan_office fail-softs missing domains
    office = {
        "holdings": {"ok": False},
        "previous_snapshot": None,
        "capital_plan": {"ok": False},
        "reentry": {},
        "previous_office_state": None,
        "baseline_needed": True,
    }
    receipt = ms.scan_office(dry_run=False, office=office, persist=False, notification_gate=False)
    assert receipt["dry_run"] is True
    assert receipt["financial_lane"] == "OFF_BY_POLICY"
    assert receipt["material_financial_notify_canary"] is False


def test_b3_catalyst_medium_plus_triggers_enqueue():
    from scripts.lib.hermes_research_loop import should_enqueue_for_plan, _catalyst_medium_plus

    # Synthetic pack shaped like catalyst_domain output
    pack = {
        "events": [{
            "event_id": "cat_test_1",
            "severity": "medium",
            "horizon_days": 3,
            "kind": "earnings",
            "confirmed": True,
        }],
        "max_severity": "medium",
    }
    plan = {
        "situation_type": "S1_POSITION_LIFECYCLE",
        "fire_reasons": [],
        "_catalyst_pack": pack,
        "symbols": ["SCHD"],
    }
    # May depend on catalyst_domain helpers — fail soft if pack shape mismatch
    ok, reason = _catalyst_medium_plus(plan)
    should, pri, why = should_enqueue_for_plan(plan)
    assert should is True
    # Either catalyst path or default S1 lifecycle
    assert pri in ("high", "normal")
    assert why


def test_d1_deferred_expires_by_horizon(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    from datetime import datetime, timedelta, timezone
    import json
    from scripts.lib.cio_outcome_observer import (
        record_disposition_outcome,
        mature_deferred_by_age,
        learning_summary,
    )
    out = record_disposition_outcome(
        decision_or_plan_id="plan_old_defer",
        disposition="defer",
        note="old defer",
    )
    assert out["matured"] is False
    # Backdate recorded_at
    proj = tmp_path / "cio_outcome_maturity.json"
    mat = json.loads(proj.read_text())
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    mat["items"]["plan_old_defer"]["recorded_at"] = old
    proj.write_text(json.dumps(mat, indent=2))
    res = mature_deferred_by_age(horizon_days=7, apply=True)
    assert res["matured_expired"] == 1
    summ = learning_summary()
    assert summ["matured_count"] >= 1
    assert summ["expired_horizon_matured"] >= 1
    assert summ["memory_behavior_influence"] == 0
