"""Typed broker-vs-analytical residuals. Never overwrite one source with another.

A $2 source-time residual with two clocks is institutionally correct.
A $0 residual produced by rewriting broker MV is not.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from typing import Any, Optional

from scripts.lib.cio_canonical_quote import _dollar_tol, _opt_fnum, _shares_of

ALIGNED_SAME_SOURCE_TIME = "ALIGNED_SAME_SOURCE_TIME"
EXPECTED_SOURCE_TIMESTAMP_DIFFERENCE = "EXPECTED_SOURCE_TIMESTAMP_DIFFERENCE"
BROKER_POSITION_SNAPSHOT_STALE = "BROKER_POSITION_SNAPSHOT_STALE"
CANONICAL_MARK_STALE = "CANONICAL_MARK_STALE"
GENUINE_MARK_CONFLICT = "GENUINE_MARK_CONFLICT"
ARITHMETIC_INCONSISTENCY = "ARITHMETIC_INCONSISTENCY"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
PROXY_USED_FOR_VALUATION = "PROXY_USED_FOR_VALUATION"
HIDDEN_RESIDUAL_INJECTION = "HIDDEN_RESIDUAL_INJECTION"

MATERIAL_RESIDUALS = frozenset({
    GENUINE_MARK_CONFLICT,
    ARITHMETIC_INCONSISTENCY,
    PROXY_USED_FOR_VALUATION,
    HIDDEN_RESIDUAL_INJECTION,
})

# Source-time residuals are notes, not G5 material conflicts.
NOTE_RESIDUALS = frozenset({
    ALIGNED_SAME_SOURCE_TIME,
    EXPECTED_SOURCE_TIMESTAMP_DIFFERENCE,
    BROKER_POSITION_SNAPSHOT_STALE,
    CANONICAL_MARK_STALE,
    DATA_UNAVAILABLE,
})


def _f(v: Any) -> Optional[float]:
    return _opt_fnum(v)


def classify_valuation_residual(row: dict[str, Any], *, now=None) -> dict[str, Any]:
    """Compare broker MV to analytical MV without forcing them equal."""
    shares = _shares_of(row)
    broker_mv = _f(row.get("broker_market_value"))
    if broker_mv is None and str(row.get("mv_basis") or "") != "shares_x_canonical_mark":
        broker_mv = _f(row.get("market_value") if row.get("market_value") is not None else row.get("value"))
    broker_px = _f(row.get("broker_position_price") or row.get("broker_price"))
    mark = _f(row.get("canonical_mark"))
    analytical = _f(row.get("analytical_market_value"))
    if analytical is None and shares is not None and mark is not None:
        analytical = shares * mark
    proxy = bool(row.get("proxy") or row.get("not_for_valuation") or str(row.get("canonical_mark_type") or "").lower() == "proxy")
    mark_used_for_mv = (
        str(row.get("mv_basis") or "") == "shares_x_canonical_mark"
        or bool(row.get("_canonical_reconcile"))
    )

    from scripts.lib.cio_financial_truth_gate import parse_ts  # local to avoid import cycle

    broker_as_of = row.get("broker_position_as_of") or row.get("broker_as_of")
    mark_as_of = row.get("canonical_mark_as_of") or row.get("source_as_of")
    broker_dt = parse_ts(broker_as_of)
    mark_dt = parse_ts(mark_as_of)

    status = ALIGNED_SAME_SOURCE_TIME
    material = False
    abs_err = None
    if proxy and mark_used_for_mv:
        status = PROXY_USED_FOR_VALUATION
        material = True
    elif broker_px is not None and shares is not None and shares > 0 and broker_mv is not None:
        implied_broker = shares * broker_px
        tol = _dollar_tol(broker_mv)
        if abs(implied_broker - broker_mv) > tol:
            status = ARITHMETIC_INCONSISTENCY
            material = True
            abs_err = abs(implied_broker - broker_mv)
    if not material and broker_mv is not None and analytical is not None:
        tol = _dollar_tol(broker_mv)
        abs_err = abs(analytical - broker_mv)
        if abs_err <= tol:
            status = ALIGNED_SAME_SOURCE_TIME
        elif broker_dt is None and mark_dt is None:
            status = EXPECTED_SOURCE_TIMESTAMP_DIFFERENCE
            # still a note: two independent facts, clocks missing → not a dual-mark conflict
        elif broker_dt and mark_dt and broker_dt != mark_dt:
            status = EXPECTED_SOURCE_TIMESTAMP_DIFFERENCE
        elif broker_dt and mark_dt:
            status = ALIGNED_SAME_SOURCE_TIME if abs_err <= tol else EXPECTED_SOURCE_TIMESTAMP_DIFFERENCE
        elif broker_dt is None:
            status = BROKER_POSITION_SNAPSHOT_STALE
        else:
            status = CANONICAL_MARK_STALE

    return {
        "symbol": str(row.get("symbol") or "").upper(),
        "account": row.get("account"),
        "broker_market_value": broker_mv,
        "broker_position_price": broker_px,
        "broker_position_as_of": str(broker_as_of) if broker_as_of else None,
        "canonical_mark": mark,
        "canonical_mark_source": row.get("canonical_mark_source"),
        "canonical_mark_as_of": str(mark_as_of) if mark_as_of else None,
        "analytical_market_value": None if analytical is None else round(float(analytical), 4),
        "valuation_residual_usd": None if abs_err is None else round(float(abs_err), 4),
        "residual_status": status,
        "material": material or status in MATERIAL_RESIDUALS,
        "proxy": proxy,
        "source_clocks_distinct": bool(broker_dt and mark_dt and broker_dt != mark_dt),
    }
