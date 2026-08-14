"""Phase 3 — named price lineage (canonical mark vs implied-from-MV).

Authority: READ_ONLY_ADVISORY. Pure unit tests, no broker / Telegram.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_canonical_quote import (  # noqa: E402
    apply_canonical_quote_fields,
    classify_row_conflicts,
)
from scripts.lib.cio_financial_truth_gate import (  # noqa: E402
    STATE_CONFLICTED,
    STATE_VERIFIED_AS_OF,
    check_position_row,
    classify_price_fields,
)


def _types(result) -> set[str]:
    return {e["type"] for e in result.get("exceptions") or []}


def _labels(result) -> set[str]:
    return {e.get("label") for e in result.get("exceptions") or [] if e.get("label")}


def test_dxcm_shape_implied_from_mv_not_dual_price():
    """225 sh, Finviz last vs MV/shares — not two marks."""
    row = {
        "symbol": "DXCM",
        "account": "schwab_rollover_ira",
        "shares": 225.0,
        "current_price": 89.73,
        "price": 89.905,
        "market_value": 20228.63,
        "price_source": "finviz",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    named = apply_canonical_quote_fields(row)
    implied = 20228.63 / 225.0
    assert named["implied_price_from_mv"] is not None
    assert abs(named["implied_price_from_mv"] - implied) < 1e-6
    assert abs(named["canonical_mark"] - 89.73) < 1e-9
    assert named["conflicted"] is False
    assert named["mv_basis"] == "broker"

    conflicts = classify_row_conflicts(row)
    assert conflicts["dual_price_conflict"] is False
    assert conflicts["implied_from_mv_recognized"] is True
    assert conflicts["broker_mv_uses_different_mark"] is True
    assert conflicts["conflicted"] is False

    r = check_position_row(row, portfolio_value=1_284_243.30)
    types = _types(r)
    assert "dual_price_conflict" not in types
    # Independent broker MV vs mark is a typed residual note, not CONFLICTED.
    assert "shares_x_price_ne_mv" not in types
    notes = r.get("reconciliation_notes") or []
    assert notes
    assert r["mv_basis"] == "broker"
    assert r["quality"] == STATE_VERIFIED_AS_OF
    assert abs(r["canonical_price"] - 89.73) < 1e-9


def test_noc_shape_price_is_market_value_not_a_mark():
    """Fractional share: price field holds MV, current_price is the real mark."""
    row = {
        "symbol": "NOC",
        "account": "schwab_rollover_ira",
        "shares": 0.2317,
        "current_price": 584.43,
        "price": 135.42,
        "market_value": 135.42,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    named = apply_canonical_quote_fields(row)
    implied = 135.42 / 0.2317
    assert named["implied_price_from_mv"] is not None
    assert abs(named["implied_price_from_mv"] - implied) < 1e-9
    assert abs(named["canonical_mark"] - 584.43) < 1e-9
    assert named["conflicted"] is False

    conflicts = classify_row_conflicts(row)
    assert conflicts["dual_price_conflict"] is False
    assert conflicts["price_is_not_a_mark"] is True
    assert conflicts["conflicted"] is False

    r = check_position_row(row, portfolio_value=1_284_243.30)
    types = _types(r)
    assert "dual_price_conflict" not in types
    # shares × 584.43 ≈ 135.41 vs MV 135.42 — within $1 floor
    assert "shares_x_price_ne_mv" not in types


def test_clean_row_one_mark_no_material_conflict():
    row = {
        "symbol": "AAA",
        "account": "ira",
        "shares": 10.0,
        "current_price": 100.0,
        "price": 100.0,
        "market_value": 1000.0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    named = apply_canonical_quote_fields(row)
    assert abs(named["canonical_mark"] - 100.0) < 1e-9
    assert named["conflicted"] is False
    assert abs(named["implied_price_from_mv"] - 100.0) < 1e-9

    conflicts = classify_row_conflicts(row)
    assert conflicts["dual_price_conflict"] is False
    assert conflicts["broker_mv_uses_different_mark"] is False
    assert conflicts["conflicted"] is False

    r = check_position_row(row, portfolio_value=10_000.0)
    assert r["exceptions"] == []
    assert r["quality"] == STATE_VERIFIED_AS_OF
    assert r["mv_basis"] in ("broker", "shares_x_canonical_mark")


def test_two_genuine_marks_dual_price_conflict():
    """current_price vs last, neither equals MV/shares → two marks."""
    row = {
        "symbol": "BBB",
        "account": "taxable",
        "shares": 10.0,
        "current_price": 100.0,
        "last": 90.0,
        "market_value": 950.0,  # implied 95; neither 100 nor 90
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    named = apply_canonical_quote_fields(row)
    assert named["conflicted"] is True
    implied = 950.0 / 10.0
    assert abs(named["implied_price_from_mv"] - implied) < 1e-9

    conflicts = classify_row_conflicts(row)
    assert conflicts["dual_price_conflict"] is True
    assert conflicts["conflicted"] is True

    r = check_position_row(row, portfolio_value=10_000.0)
    types = _types(r)
    assert "dual_price_conflict" in types


def test_apply_does_not_mutate_input():
    row = {"symbol": "X", "shares": 1.0, "current_price": 10.0, "market_value": 10.0}
    out = apply_canonical_quote_fields(row)
    assert out is not row
    assert "canonical_mark" not in row
    assert out["canonical_mark"] == 10.0


def test_classify_price_fields_uses_named_semantics():
    """Gate helper must not treat implied-from-MV as a second current mark."""
    row = {
        "symbol": "DXCM",
        "shares": 225.0,
        "current_price": 89.73,
        "price": 89.905,
        "market_value": 20228.63,
    }
    info = classify_price_fields(row)
    assert info["conflicted"] is False
    assert abs(info["canonical_price"] - 89.73) < 1e-9
