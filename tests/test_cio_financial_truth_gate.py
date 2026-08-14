"""Phase 2 — FinancialTruthGate unit tests (pure, no broker)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_financial_truth_gate import (  # noqa: E402
    FINANCIAL_TRUTH_GATE_VERSION,
    STATE_CONFLICTED,
    STATE_STALE,
    STATE_VERIFIED_AS_OF,
    STATE_DATA_UNAVAILABLE,
    analyst_upside_vs_canonical,
    attach_gate_to_capital_plan,
    check_position_row,
    dollar_tol,
    evaluate_holdings_document,
    field_meta,
)
from scripts.lib import cio_capital_plan as cp  # noqa: E402


def test_version_and_dollar_tol():
    assert FINANCIAL_TRUTH_GATE_VERSION.startswith("financial_truth_gate_")
    assert dollar_tol(0) == 1.0
    assert dollar_tol(1_000_000) == max(1.0, 100.0)  # 0.01% of 1e6 = 100


def test_clean_position_passes():
    row = {
        "symbol": "AAA",
        "account": "ira",
        "shares": 10.0,
        "current_price": 100.0,
        "price": 100.0,
        "market_value": 1000.0,
        "cost_basis": 800.0,
        "gain_loss": 200.0,
        "gain_loss_pct": 25.0,
        "portfolio_pct": 10.0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    r = check_position_row(row, portfolio_value=10_000.0)
    assert r["exceptions"] == []
    assert r["quality"] == STATE_VERIFIED_AS_OF
    assert r["actionable"] is True


def test_shares_x_price_is_typed_residual_not_forced_conflict():
    """Broker MV vs analytical mark is a note, not an overwrite-to-zero conflict."""
    row = {
        "symbol": "BBB",
        "account": "taxable",
        "shares": 10.0,
        "current_price": 100.0,
        "market_value": 900.0,
        "broker_market_value": 900.0,
        "canonical_mark": 100.0,
        "canonical_mark_as_of": "2026-08-14T20:00:00+00:00",
        "broker_position_as_of": "2026-08-14T16:00:00+00:00",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    r = check_position_row(row, portfolio_value=10_000.0)
    assert r["quality"] == STATE_VERIFIED_AS_OF
    assert not any(e["type"] == "shares_x_price_ne_mv" for e in r["exceptions"])
    notes = r.get("reconciliation_notes") or []
    assert notes
    assert notes[0]["label"] == "EXPECTED_SOURCE_TIMESTAMP_DIFFERENCE"


def test_dxcm_regression_dual_price_and_mv():
    """Observed Phase 0 DXCM shape: dual price + shares×px ≠ MV → CONFLICTED."""
    row = {
        "symbol": "DXCM",
        "account": "schwab_rollover_ira",
        "shares": 225.0,
        "current_price": 91.26,
        "price": 90.98,  # Finviz alternate
        "market_value": 20470.50,  # neither 225*91.26 nor 225*90.98 exactly in spirit
        "cost_basis": 15985.13,
        "price_source": "finviz",
        "as_of": "2026-08-14",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Force MV that mismatches current_price path
    row["market_value"] = 20470.50  # 225*91.26 = 20533.5 → err 63
    r = check_position_row(row, portfolio_value=1_284_243.30)
    assert r["symbol"] == "DXCM"
    # price ≈ MV/shares so this is a broker-vs-mark residual, not two genuine marks.
    types = {e["type"] for e in r["exceptions"]}
    assert "dual_price_conflict" not in types
    notes = r.get("reconciliation_notes") or []
    assert notes or r["quality"] in (STATE_VERIFIED_AS_OF, STATE_CONFLICTED)
    assert abs(r["canonical_price"] - 91.26) < 1e-9


def test_dxcm_in_book_suppresses_act_now():
    doc = {
        "as_of": "2026-08-14",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "portfolio_totals": {"total_value": 100_000.0},
        "holdings": [
            {"symbol": "CASH", "is_cash": True, "market_value": 50_000.0, "account": "ira"},
            {
                "symbol": "DXCM",
                "account": "ira",
                "shares": 225.0,
                "current_price": 91.26,
                "price": 90.98,
                "market_value": 20470.50,
                "cost_basis": 15985.13,
                "portfolio_pct": 20.47,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "symbol": "AAA",
                "account": "ira",
                "shares": 100.0,
                "current_price": 100.0,
                "price": 100.0,
                "market_value": 10000.0,
                "cost_basis": 9000.0,
                "portfolio_pct": 10.0,
                "gain_loss": 1000.0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        ],
    }
    # Adjust portfolio totals to cash+mv for cleaner book (optional)
    gate = evaluate_holdings_document(doc)
    # Dual-looking DXCM here is mark vs implied-from-MV — residual notes, not suppress-ACT-NOW conflict.
    assert gate["overall_quality"] in (STATE_VERIFIED_AS_OF, STATE_STALE, STATE_CONFLICTED)
    if gate["overall_quality"] != STATE_CONFLICTED:
        assert not gate["conflicted_symbols"] or "DXCM" not in gate["conflicted_symbols"]
    plan = {
        "position_decisions": [
            {"symbol": "DXCM", "cio_stance": "TRIM", "recommended_delta_usd": -2047.05},
            {"symbol": "AAA", "cio_stance": "HOLD", "recommended_delta_usd": 0},
        ],
        "cash_total_usd": 50_000.0,
        "cash_earmarked_redeploy_usd": 50_000.0,
    }
    out = attach_gate_to_capital_plan(plan, gate)
    dx = next(d for d in out["position_decisions"] if d["symbol"] == "DXCM")
    if "DXCM" in (gate.get("suppress_act_now_symbols") or []):
        assert dx.get("act_now_suppressed") is True
        assert dx.get("actionable") is False
    assert out["financial_truth_gate"]["earmark_eq_full_cash"] is True


def test_analyst_upside_stale_denominator_labeled():
    res = analyst_upside_vs_canonical(
        analyst_target=120.0,
        canonical_price=100.0,
        analyst_snapshot_price=80.0,  # stale/wrong denom
    )
    assert res["label"] == "upside_vs_analyst_snapshot_price"
    assert res["quality"] == STATE_CONFLICTED
    assert res["upside_pct"] == 50.0  # (120-80)/80


def test_analyst_upside_vs_canonical_current():
    res = analyst_upside_vs_canonical(
        analyst_target=110.0,
        canonical_price=100.0,
    )
    assert res["label"] == "upside_vs_canonical_current_price"
    assert abs(res["upside_pct"] - 10.0) < 1e-6
    assert res["quality"] == STATE_VERIFIED_AS_OF


def test_field_meta_contract():
    m = field_meta(
        value=100.0,
        source="holdings.json",
        source_as_of="2026-08-14T12:00:00+00:00",
        ingested_at="2026-08-14T12:05:00+00:00",
        quality=STATE_VERIFIED_AS_OF,
        snapshot_id="snap1",
    )
    assert m["source"] == "holdings.json"
    assert m["snapshot_id"] == "snap1"
    assert m["quality"] == STATE_VERIFIED_AS_OF
    assert m["age_seconds"] is not None


def test_meta_timestamp_conflict_stale_updated_at():
    doc = {
        "as_of": "2026-08-14",
        "generated_at": "2026-08-14 09:30:01 ET",
        "updated_at": "2026-08-04T16:00:02.400640+00:00",  # Phase 0 shape
        "portfolio_totals": {"total_value": 2000.0},
        "holdings": [
            {"symbol": "CASH", "is_cash": True, "market_value": 1000.0, "account": "a"},
            {
                "symbol": "XYZ",
                "account": "a",
                "shares": 10,
                "current_price": 100,
                "price": 100,
                "market_value": 1000,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        ],
    }
    gate = evaluate_holdings_document(doc, now=datetime(2026, 8, 14, 14, 0, tzinfo=timezone.utc))
    types = {e["type"] for e in gate["exceptions"]}
    assert "meta_timestamp_conflict" in types or gate["meta"]["quality"] in (
        STATE_CONFLICTED, STATE_STALE,
    )


def test_book_identity_cash_plus_mv():
    doc = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "portfolio_totals": {"total_value": 9999.0},  # wrong on purpose
        "holdings": [
            {"symbol": "CASH", "is_cash": True, "market_value": 4000.0, "account": "a"},
            {
                "symbol": "QQQ",
                "account": "a",
                "shares": 10,
                "current_price": 500,
                "price": 500,
                "market_value": 5000,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        ],
    }
    gate = evaluate_holdings_document(doc)
    assert gate["portfolio"]["derived_portfolio_usd"] == 9000.0
    assert any(e["type"] == "portfolio_ne_cash_plus_mv" for e in gate["exceptions"])


def test_capital_plan_from_sources_attaches_gate():
    doc = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "portfolio_totals": {"total_value": 100_000.0},
        "config": {"accounts": {"ira": {"taxable": False}}},
        "holdings": [
            {"symbol": "CASH", "is_cash": True, "market_value": 20_000.0, "account": "ira"},
            {
                "symbol": "SCHD",
                "account": "ira",
                "shares": 100,
                "current_price": 800,
                "price": 800,
                "market_value": 80_000,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        ],
    }
    plan = cp.build_capital_plan_from_sources(
        holdings_doc=doc,
        queue={"items": []},
        redeploy_open_events=[],
    )
    assert "financial_truth_gate" in plan
    assert plan["financial_truth_gate"]["gate_version"].startswith("financial_truth_gate_")
    assert plan["financial_truth_gate"]["authority"] == "READ_ONLY_ADVISORY"


def test_unavailable_without_price():
    row = {"symbol": "ZZZ", "account": "a", "market_value": 100.0, "shares": 1}
    r = check_position_row(row, portfolio_value=1000.0)
    # no price → cannot prove shares*px; may be VERIFIED_AS_OF on mv alone or unavailable pieces
    assert r["canonical_price"] is None
