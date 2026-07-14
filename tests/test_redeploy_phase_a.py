#!/usr/bin/env python3
"""Phase A acceptance — FCNTX event facts and proceeds reconciliation."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_fcntx_holdings_stale_not_broker_unsettled():
    """Sale 2026-07-14 with holdings as_of 2026-07-13 — sync lag, not broker unsettled."""
    dt = _load("redeploy_data_truth", "scripts/lib/redeploy_data_truth.py")
    recon = dt.reconcile_proceeds(
        account="schwab_rollover_ira",
        proceeds_usd=107023.01,
        cash_visible_usd=17540.67,
        sold_at="2026-07-14",
    )
    assert recon["reconciliation_status"] == "holdings_stale"
    assert recon["deployable_cash_usd"] == 107023.01
    assert recon["planned_not_actionable_usd"] == 0.0


def test_fcntx_operator_verified_full_settlement():
    dt = _load("redeploy_data_truth", "scripts/lib/redeploy_data_truth.py")
    recon = dt.reconcile_proceeds(
        account="schwab_rollover_ira",
        proceeds_usd=107023.01,
        cash_visible_usd=17540.67,
        sold_at="2026-07-14",
        operator_settlement={"verified": True, "settled_cash_usd": 107023.01},
    )
    assert recon["reconciliation_status"] == "verified"
    assert recon["deployable_cash_usd"] == 107023.01


def test_fcntx_income_unknown_not_zero():
    dt = _load("redeploy_data_truth", "scripts/lib/redeploy_data_truth.py")
    exp = dt.decompose_exposure_loss(symbol="FCNTX", proceeds_usd=107023.01, proxy_symbol="SCHG")
    assert exp["income_status"] == "unknown"
    assert exp["income_annual_usd"] is None


def test_fcntx_sector_decomposition_sums_to_100():
    dt = _load("redeploy_data_truth", "scripts/lib/redeploy_data_truth.py")
    exp = dt.decompose_exposure_loss(symbol="FCNTX", proceeds_usd=107023.01)
    accounted = sum(s["weight_pct"] for s in exp["sectors"])
    assert accounted >= 99.0
    assert accounted <= 100.5
    assert (exp.get("residual_sector_pct") or 0) < 1.0


def test_fcntx_brk_share_class_note():
    dt = _load("redeploy_data_truth", "scripts/lib/redeploy_data_truth.py")
    exp = dt.decompose_exposure_loss(symbol="FCNTX", proceeds_usd=107023.01)
    brk = next((h for h in exp["top_holdings"] if h["ticker"] in ("BRK.A", "BRK.B")), None)
    assert brk is not None
    assert brk.get("share_class_note")


def test_fcntx_major_sale_classification():
    dt = _load("redeploy_data_truth", "scripts/lib/redeploy_data_truth.py")
    major = dt.classify_major_sale(
        proceeds_usd=107023.01,
        portfolio_equity_usd=984178.81,
        instrument_type="mutual_fund",
        exposure_pct_of_portfolio=10.87,
    )
    assert major["is_major_sale"]
    assert "mutual_fund" in major["reasons"]


def test_plan_archetypes_seven_distinct():
    dt = _load("redeploy_data_truth", "scripts/lib/redeploy_data_truth.py")
    assert set(dt.PLAN_ARCHETYPES.keys()) == set("ABCDEFG")
    assert dt.PLAN_ARCHETYPES["F"][0] == "staged_deployment"
    assert dt.PLAN_ARCHETYPES["G"][0] == "hold_no_redeploy"


def test_enrich_event_phase_a_metadata():
    dt = _load("redeploy_data_truth", "scripts/lib/redeploy_data_truth.py")
    ev = {
        "event_key": "test:fcntx",
        "symbol": "FCNTX",
        "account": "schwab_rollover_ira",
        "sold_at": "2026-07-14",
        "proceeds_usd": 107023.01,
        "cash_visible_usd": 17540.67,
        "proxy_symbol": "SCHG",
        "instrument_type": "mutual_fund",
    }
    out = dt.enrich_event_phase_a(ev)
    pa = out["metadata"]["phase_a"]
    assert pa["reconciliation"]["reconciliation_status"] == "holdings_stale"
    assert pa["reconciliation"]["deployable_cash_usd"] == 107023.01
    assert pa["portfolio_context"]["portfolio_equity_usd"] > 900000
    assert pa["portfolio_context"]["default_deployment_account"] == "schwab_rollover_ira"


if __name__ == "__main__":
    tests = [
        test_fcntx_holdings_stale_not_broker_unsettled,
        test_fcntx_operator_verified_full_settlement,
        test_fcntx_income_unknown_not_zero,
        test_fcntx_sector_decomposition_sums_to_100,
        test_fcntx_brk_share_class_note,
        test_fcntx_major_sale_classification,
        test_plan_archetypes_seven_distinct,
        test_enrich_event_phase_a_metadata,
    ]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"ALL {len(tests)} PASSED")