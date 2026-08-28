"""Slice 8: OutcomeCheckpoint for held researched plans. Skip CASH sleeve."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.lib.cio_plan_outcome_checkpoints import (
    bind_held_researched_plan_checkpoints,
    skip_reason,
)
from scripts.lib.cio_plans import CIOPlanStore


def _store(tmp: Path) -> CIOPlanStore:
    return CIOPlanStore(event_path=tmp / "cio_plans.jsonl", projection_path=tmp / "cio_plans_projection.json")


def _opts():
    return [{"id": "hold", "label": "Hold"}, {"id": "trim", "label": "Trim"}]


def test_cash_sleeve_not_priced_as_pathward(tmp_path):
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    store.create_plan(
        situation_type="S5_CASH_DEPLOYMENT",
        symbols=["CASH"],
        title="cash sleeve",
        options=_opts(),
        recommendation="HOLD_CASH",
        evidence_refs=[{"domain": "cash_buying_power"}],
        revisit_at=(now + timedelta(days=1)).isoformat(),
        owner_agent="alex",
        extra={"hermes_result_id": "rr_cash"},
    )
    rec = bind_held_researched_plan_checkpoints(
        root=tmp_path, store=store,
        holdings={"holdings": [{"symbol": "CASH", "is_cash": True, "market_value": 1000}]},
        apply=True,
    )
    assert rec["eligible_n"] == 0
    assert rec["wrote_n"] == 0
    assert rec["skipped_reasons"].get("s5_cash_deployment") or rec["skipped_reasons"].get("cash_sleeve") or rec["skipped_reasons"].get("non_security_recommendation")
    ck = tmp_path / "data" / "cio" / "outcome_checkpoints.jsonl"
    assert not ck.exists() or "CASH" not in ck.read_text() or "Pathward" not in ck.read_text()


def test_held_schd_fixture_can_bind(tmp_path):
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    store.create_plan(
        situation_type="S6_CONCENTRATION_OR_DISPOSITION",
        symbols=["SCHD"],
        title="SCHD concentration",
        options=_opts(),
        recommendation="Hold pending research",
        evidence_refs=[{"domain": "holdings_detail"}],
        revisit_at=(now + timedelta(days=1)).isoformat(),
        owner_agent="alex",
        extra={"hermes_result_id": "rr_schd"},
    )
    holdings = {"holdings": [{"symbol": "SCHD", "market_value": 50000}, {"symbol": "CASH", "is_cash": True, "market_value": 1000}]}
    rec = bind_held_researched_plan_checkpoints(
        root=tmp_path, store=store, holdings=holdings, apply=True,
    )
    assert rec["eligible_n"] == 1
    assert rec["wrote_n"] >= 1
    assert rec["samples"][0]["symbol"] == "SCHD"
    ck = tmp_path / "data" / "cio" / "outcome_checkpoints.jsonl"
    text = ck.read_text()
    assert "OutcomeCheckpoint@v1" in text
    assert "SCHD" in text
    assert rec["observational_only"] is True
    assert rec["financial_action"] is False


def test_unheld_symbol_skipped(tmp_path):
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    plan = store.create_plan(
        situation_type="S1_POSITION_LIFECYCLE",
        symbols=["NKE"],
        title="nke watch",
        options=_opts(),
        recommendation="WATCH",
        evidence_refs=[{"domain": "watch"}],
        revisit_at=(now + timedelta(days=1)).isoformat(),
        owner_agent="alex",
        extra={"hermes_result_id": "rr_nke"},
    )
    assert skip_reason(plan, {"SCHD"}) == "not_held"
