"""cio_financial_truth_gate.py — Phase 2 FinancialTruthGate (acceptance).

Reusable, pure reconciliation of holdings / cash / weights / P&L before Alex
may treat numbers as actionable.

Publication states (per field / row / book):
  VERIFIED_CURRENT | VERIFIED_AS_OF | STALE | CONFLICTED | DATA_UNAVAILABLE

Does NOT mutate holdings, place orders, or call brokers.
Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from scripts.lib.cio_canonical_quote import (  # noqa: E402
    apply_canonical_quote_fields,
    classify_row_conflicts,
)

FINANCIAL_TRUTH_GATE_VERSION = "financial_truth_gate_1.0.0"

# Publication states (operator-facing)
STATE_VERIFIED_CURRENT = "VERIFIED_CURRENT"
STATE_VERIFIED_AS_OF = "VERIFIED_AS_OF"
STATE_STALE = "STALE"
STATE_CONFLICTED = "CONFLICTED"
STATE_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"

PUBLICATION_STATES = frozenset({
    STATE_VERIFIED_CURRENT,
    STATE_VERIFIED_AS_OF,
    STATE_STALE,
    STATE_CONFLICTED,
    STATE_DATA_UNAVAILABLE,
})

# Tolerances (Phase 0 / acceptance prompt)
DOLLAR_FLOOR_TOL = 1.0  # max($1, 0.01% of row)
DOLLAR_PCT_TOL = 0.0001  # 0.01% of row value
WEIGHT_PP_TOL = 0.02  # percentage points
PRICE_DERIVED_PCT_TOL = 0.001  # 0.1%

# Freshness (seconds) — quote/MV intraday default; holdings meta lag
QUOTE_STALE_SEC_RTH = 15 * 60
HOLDINGS_META_STALE_SEC = 48 * 3600
DEFAULT_AS_OF_STALE_SEC = 24 * 3600


def _fnum(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _opt_fnum(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def dollar_tol(row_value: float) -> float:
    return max(DOLLAR_FLOOR_TOL, abs(row_value) * DOLLAR_PCT_TOL)


def parse_ts(value: Any) -> Optional[datetime]:
    """Parse ISO-ish timestamps; return aware UTC or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    # date-only
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            return datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]), tzinfo=timezone.utc)
        except ValueError:
            return None
    # strip trailing " ET" etc.
    for suffix in (" ET", " EST", " EDT", " UTC"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def age_seconds(ts: Optional[datetime], *, now: Optional[datetime] = None) -> Optional[float]:
    if ts is None:
        return None
    n = now or datetime.now(timezone.utc)
    return max(0.0, (n - ts).total_seconds())


def field_meta(
    *,
    value: Any,
    source: str,
    source_as_of: Any = None,
    ingested_at: Any = None,
    quality: str = STATE_VERIFIED_AS_OF,
    calculation_version: str = FINANCIAL_TRUTH_GATE_VERSION,
    snapshot_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Timestamp contract for one operator-facing financial field."""
    sa = parse_ts(source_as_of)
    ia = parse_ts(ingested_at)
    age = age_seconds(sa or ia, now=now)
    q = quality if quality in PUBLICATION_STATES else STATE_DATA_UNAVAILABLE
    return {
        "value": value,
        "source": source,
        "source_as_of": sa.isoformat() if sa else (str(source_as_of) if source_as_of else None),
        "ingested_at": ia.isoformat() if ia else (str(ingested_at) if ingested_at else None),
        "age_seconds": round(age, 1) if age is not None else None,
        "quality": q,
        "calculation_version": calculation_version,
        "snapshot_id": snapshot_id,
    }


def classify_price_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Detect dual / conflicting *genuine marks* on one holdings row.

    Implied-from-MV and MV stuffed into `price` are not marks. Dual-price
    fires only when two genuine marks disagree (see cio_canonical_quote).
    """
    named = apply_canonical_quote_fields(row)
    conflicts = classify_row_conflicts(named)
    genuine = dict(conflicts.get("genuine_marks") or {})
    # Keep a raw map for diagnostics (includes non-marks) without using it
    # for conflict — callers that need lineage should use named fields.
    raw_prices: dict[str, float] = {}
    for key in ("current_price", "price", "last", "mark", "close"):
        v = _opt_fnum(row.get(key))
        if v is not None and v > 0:
            raw_prices[key] = v
    canon = named.get("canonical_mark")
    if canon is None and not raw_prices:
        return {
            "canonical_price": None,
            "canonical_price_key": None,
            "conflicted": False,
            "prices": {},
            "quality": STATE_DATA_UNAVAILABLE,
            "implied_price_from_mv": named.get("implied_price_from_mv"),
            "mv_basis": named.get("mv_basis"),
            "genuine_marks": {},
        }
    conflicted = bool(conflicts.get("dual_price_conflict"))
    return {
        "canonical_price": canon,
        "canonical_price_key": named.get("canonical_mark_source"),
        "conflicted": conflicted,
        "prices": genuine or raw_prices,
        "quality": STATE_CONFLICTED if conflicted else (
            STATE_VERIFIED_AS_OF if canon is not None else STATE_DATA_UNAVAILABLE
        ),
        "implied_price_from_mv": named.get("implied_price_from_mv"),
        "mv_basis": named.get("mv_basis"),
        "genuine_marks": genuine,
        "price_field_role": named.get("price_field_role"),
    }


def check_position_row(
    row: dict[str, Any],
    *,
    portfolio_value: float,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Per-position arithmetic + price/source consistency."""
    symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
    account = str(row.get("account") or row.get("account_id") or "")
    shares = _opt_fnum(row.get("shares") if row.get("shares") is not None else row.get("quantity") or row.get("qty"))
    mv = _opt_fnum(row.get("market_value") if row.get("market_value") is not None else row.get("value"))
    basis = _opt_fnum(row.get("cost_basis") if row.get("cost_basis") is not None else row.get("average_cost") or row.get("avg_cost"))
    weight_reported = _opt_fnum(row.get("portfolio_pct") if row.get("portfolio_pct") is not None else row.get("weight_pct"))
    upl_reported = _opt_fnum(
        row.get("unrealized_pl_usd")
        if row.get("unrealized_pl_usd") is not None
        else row.get("gain_loss") or row.get("unrealized_pl")
    )
    upl_pct_reported = _opt_fnum(row.get("gain_loss_pct") or row.get("unrealized_pl_pct"))

    named = apply_canonical_quote_fields(row)
    conflicts = classify_row_conflicts(named)
    price_info = classify_price_fields(named)
    px = named.get("canonical_mark")
    if px is None:
        px = price_info["canonical_price"]

    exceptions: list[dict[str, Any]] = []
    quality = STATE_VERIFIED_AS_OF
    mv_basis = named.get("mv_basis")

    if mv is None:
        exceptions.append({"type": "market_value_missing", "symbol": symbol, "account": account})
        quality = STATE_DATA_UNAVAILABLE
        mv = 0.0
        if shares is not None and px is not None:
            mv_basis = "shares_x_canonical_mark"

    # shares × CANONICAL MARK ≈ market_value.
    # When they disagree the broker MV is on a different mark — label that
    # honestly instead of pretending price/current_price are one "current".
    if shares is not None and shares > 0 and px is not None and px > 0:
        implied = shares * px
        tol = dollar_tol(mv or implied)
        if abs(implied - (mv or 0.0)) > tol:
            exceptions.append({
                "type": "shares_x_price_ne_mv",
                "label": "broker_mv_uses_different_mark",
                "symbol": symbol,
                "account": account,
                "shares": shares,
                "canonical_price": px,
                "canonical_mark": px,
                "canonical_price_key": named.get("canonical_mark_source") or price_info["canonical_price_key"],
                "canonical_mark_source": named.get("canonical_mark_source"),
                "prices": price_info.get("genuine_marks") or price_info["prices"],
                "implied_price_from_mv": named.get("implied_price_from_mv"),
                "implied_mv": round(implied, 4),
                "market_value": mv,
                "mv_basis": "broker",
                "abs_err": round(abs(implied - (mv or 0.0)), 4),
                "tol": round(tol, 4),
            })
            quality = STATE_CONFLICTED
            mv_basis = "broker"

    # dual_price only for two genuine marks — not mark vs implied-from-MV
    if conflicts.get("dual_price_conflict") or price_info["conflicted"]:
        exceptions.append({
            "type": "dual_price_conflict",
            "symbol": symbol,
            "account": account,
            "prices": price_info.get("genuine_marks") or price_info["prices"],
            "price_field_role": named.get("price_field_role"),
        })
        quality = STATE_CONFLICTED

    # weight
    weight_computed = None
    if portfolio_value and portfolio_value > 0 and mv is not None:
        weight_computed = (mv / portfolio_value) * 100.0
        if weight_reported is not None:
            if abs(weight_computed - weight_reported) > WEIGHT_PP_TOL:
                exceptions.append({
                    "type": "weight_mismatch",
                    "symbol": symbol,
                    "account": account,
                    "reported_weight_pct": weight_reported,
                    "computed_weight_pct": round(weight_computed, 4),
                    "abs_err_pp": round(abs(weight_computed - weight_reported), 4),
                })
                if quality != STATE_CONFLICTED:
                    quality = STATE_CONFLICTED

    # unrealized P/L
    upl_computed = None
    upl_pct_computed = None
    if basis is not None and basis > 0 and mv is not None:
        upl_computed = mv - basis
        upl_pct_computed = (upl_computed / basis) * 100.0
        if upl_reported is not None:
            tol = dollar_tol(abs(upl_computed) if upl_computed else abs(mv))
            if abs(upl_reported - upl_computed) > tol:
                exceptions.append({
                    "type": "upl_mismatch",
                    "symbol": symbol,
                    "account": account,
                    "reported": upl_reported,
                    "computed": round(upl_computed, 4),
                    "abs_err": round(abs(upl_reported - upl_computed), 4),
                })
                if quality not in (STATE_CONFLICTED, STATE_DATA_UNAVAILABLE):
                    quality = STATE_CONFLICTED
        if upl_pct_reported is not None and upl_pct_computed is not None:
            if abs(upl_pct_reported - upl_pct_computed) > 0.15:  # 0.15 pp on %
                exceptions.append({
                    "type": "upl_pct_mismatch",
                    "symbol": symbol,
                    "account": account,
                    "reported_pct": upl_pct_reported,
                    "computed_pct": round(upl_pct_computed, 4),
                })

    # timestamps on row
    as_of = row.get("as_of") or row.get("price_as_of") or row.get("quote_time")
    updated = row.get("updated_at") or row.get("ingested_at")
    ts_updated = parse_ts(updated)
    age = age_seconds(ts_updated, now=now)
    if age is not None and age > QUOTE_STALE_SEC_RTH * 8:  # >2h hard stale for row update
        if quality == STATE_VERIFIED_AS_OF:
            quality = STATE_STALE
        exceptions.append({
            "type": "row_timestamp_stale",
            "symbol": symbol,
            "account": account,
            "age_seconds": round(age, 1),
            "updated_at": updated,
        })

    actionable = quality in (STATE_VERIFIED_CURRENT, STATE_VERIFIED_AS_OF)
    return {
        "symbol": symbol,
        "account": account,
        "shares": shares,
        "market_value": mv,
        "canonical_price": px,
        "canonical_mark": px,
        "canonical_price_key": named.get("canonical_mark_source") or price_info.get("canonical_price_key"),
        "canonical_mark_source": named.get("canonical_mark_source"),
        "canonical_mark_type": named.get("canonical_mark_type"),
        "implied_price_from_mv": named.get("implied_price_from_mv"),
        "mv_basis": mv_basis,
        "cost_basis": basis,
        "weight_pct_reported": weight_reported,
        "weight_pct_computed": round(weight_computed, 4) if weight_computed is not None else None,
        "unrealized_pl_usd_computed": round(upl_computed, 4) if upl_computed is not None else None,
        "unrealized_pl_pct_computed": round(upl_pct_computed, 4) if upl_pct_computed is not None else None,
        "quality": quality,
        "actionable": actionable,
        "exceptions": exceptions,
        "price_fields": price_info.get("genuine_marks") or price_info.get("prices") or {},
        "source": row.get("source") or row.get("price_source"),
        "as_of": as_of,
        "updated_at": updated,
    }


def analyst_upside_vs_canonical(
    *,
    analyst_target: Optional[float],
    canonical_price: Optional[float],
    analyst_snapshot_price: Optional[float] = None,
    label_if_stale_denominator: str = "upside_vs_analyst_snapshot_price",
) -> dict[str, Any]:
    """target_upside must use same price snapshot or be explicitly labeled."""
    if analyst_target is None or analyst_target <= 0:
        return {
            "upside_pct": None,
            "denominator_price": None,
            "label": "DATA_UNAVAILABLE",
            "quality": STATE_DATA_UNAVAILABLE,
        }
    if analyst_snapshot_price is not None and analyst_snapshot_price > 0:
        if canonical_price is not None and canonical_price > 0:
            rel = abs(analyst_snapshot_price - canonical_price) / canonical_price
            if rel > PRICE_DERIVED_PCT_TOL * 5:
                # denominator is not current — label honestly
                up = (analyst_target - analyst_snapshot_price) / analyst_snapshot_price * 100.0
                return {
                    "upside_pct": round(up, 4),
                    "denominator_price": analyst_snapshot_price,
                    "canonical_price": canonical_price,
                    "label": label_if_stale_denominator,
                    "quality": STATE_CONFLICTED,
                    "note": "Analyst snapshot price differs from canonical current; do not label as vs current.",
                }
        up = (analyst_target - analyst_snapshot_price) / analyst_snapshot_price * 100.0
        return {
            "upside_pct": round(up, 4),
            "denominator_price": analyst_snapshot_price,
            "label": label_if_stale_denominator,
            "quality": STATE_VERIFIED_AS_OF,
        }
    if canonical_price is None or canonical_price <= 0:
        return {
            "upside_pct": None,
            "denominator_price": None,
            "label": "DATA_UNAVAILABLE",
            "quality": STATE_DATA_UNAVAILABLE,
        }
    up = (analyst_target - canonical_price) / canonical_price * 100.0
    return {
        "upside_pct": round(up, 4),
        "denominator_price": canonical_price,
        "label": "upside_vs_canonical_current_price",
        "quality": STATE_VERIFIED_AS_OF,
    }


def _iter_holdings_rows(holdings_doc: dict[str, Any]) -> list[dict[str, Any]]:
    raw = holdings_doc.get("holdings") or holdings_doc.get("positions") or holdings_doc.get("items") or []
    if isinstance(raw, dict):
        rows: list[dict[str, Any]] = []
        for acct, items in raw.items():
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        r = dict(it)
                        r.setdefault("account", acct)
                        rows.append(r)
            elif isinstance(items, dict):
                r = dict(items)
                r.setdefault("account", acct)
                rows.append(r)
        return rows
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    return []


def evaluate_holdings_document(
    holdings_doc: Optional[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    portfolio_value_override: Optional[float] = None,
) -> dict[str, Any]:
    """Full book reconciliation against a holdings.json-shaped document."""
    now = now or datetime.now(timezone.utc)
    doc = holdings_doc or {}
    rows = _iter_holdings_rows(doc)
    totals = doc.get("portfolio_totals") or {}

    cash_rows: list[dict[str, Any]] = []
    pos_rows: list[dict[str, Any]] = []
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        is_cash = bool(r.get("is_cash") or sym in ("CASH", "USD", "CUR:USD") or "CASH" in sym)
        if is_cash:
            cash_rows.append(r)
        else:
            pos_rows.append(r)

    total_cash = round(sum(_fnum(r.get("market_value")) for r in cash_rows), 2)
    total_long_mv = round(sum(_fnum(r.get("market_value")) for r in pos_rows), 2)
    derived_portfolio = round(total_cash + total_long_mv, 2)
    reported_total = _opt_fnum(totals.get("total_value") or doc.get("total_value") or doc.get("portfolio_value"))
    portfolio_value = portfolio_value_override or reported_total or derived_portfolio

    # Account rolls
    by_acct: dict[str, dict[str, float]] = {}
    for r in rows:
        acct = str(r.get("account") or r.get("account_id") or "unknown")
        by_acct.setdefault(acct, {"cash": 0.0, "positions_mv": 0.0, "n_positions": 0})
        mv = _fnum(r.get("market_value"))
        sym = str(r.get("symbol") or "").upper()
        is_cash = bool(r.get("is_cash") or sym in ("CASH", "USD") or "CASH" in sym)
        if is_cash:
            by_acct[acct]["cash"] += mv
        else:
            by_acct[acct]["positions_mv"] += mv
            by_acct[acct]["n_positions"] += 1

    account_exceptions: list[dict[str, Any]] = []
    account_totals = []
    sum_acct = 0.0
    for acct, d in sorted(by_acct.items()):
        total = round(d["cash"] + d["positions_mv"], 2)
        sum_acct += total
        account_totals.append({
            "account": acct,
            "cash_usd": round(d["cash"], 2),
            "positions_mv_usd": round(d["positions_mv"], 2),
            "account_total_usd": total,
            "n_positions": int(d["n_positions"]),
        })

    book_exceptions: list[dict[str, Any]] = []
    # portfolio identity
    if reported_total is not None:
        tol = dollar_tol(reported_total)
        if abs(reported_total - derived_portfolio) > tol:
            book_exceptions.append({
                "type": "portfolio_ne_cash_plus_mv",
                "reported_total": reported_total,
                "cash_plus_mv": derived_portfolio,
                "abs_err": round(abs(reported_total - derived_portfolio), 4),
                "tol": round(tol, 4),
            })
    tol_acct = dollar_tol(portfolio_value or derived_portfolio)
    if abs(sum_acct - derived_portfolio) > tol_acct:
        book_exceptions.append({
            "type": "sum_accounts_ne_portfolio",
            "sum_accounts": round(sum_acct, 2),
            "derived_portfolio": derived_portfolio,
            "abs_err": round(abs(sum_acct - derived_portfolio), 4),
        })

    # Meta timestamp contract
    meta_as_of = doc.get("as_of") or doc.get("generated_at")
    meta_updated = doc.get("updated_at")
    meta_ts = parse_ts(meta_updated)
    meta_as_of_ts = parse_ts(meta_as_of)
    meta_exceptions: list[dict[str, Any]] = []
    meta_quality = STATE_VERIFIED_AS_OF
    if meta_ts and meta_as_of_ts:
        # if updated_at much older than as_of label → conflict
        if meta_ts < meta_as_of_ts and (meta_as_of_ts - meta_ts).total_seconds() > 12 * 3600:
            meta_exceptions.append({
                "type": "meta_timestamp_conflict",
                "updated_at": meta_updated,
                "as_of": meta_as_of,
                "detail": "updated_at lags as_of/generated_at by >12h",
            })
            meta_quality = STATE_CONFLICTED
    age_meta = age_seconds(meta_ts, now=now)
    if age_meta is not None and age_meta > HOLDINGS_META_STALE_SEC:
        meta_exceptions.append({
            "type": "holdings_meta_stale",
            "age_seconds": round(age_meta, 1),
            "updated_at": meta_updated,
        })
        if meta_quality != STATE_CONFLICTED:
            meta_quality = STATE_STALE

    position_results = [
        check_position_row(r, portfolio_value=portfolio_value or derived_portfolio, now=now)
        for r in pos_rows
    ]
    pos_exceptions = [e for pr in position_results for e in pr["exceptions"]]
    conflicted_symbols = sorted({
        pr["symbol"] for pr in position_results if pr["quality"] == STATE_CONFLICTED and pr["symbol"]
    })
    non_actionable = [pr for pr in position_results if not pr["actionable"]]

    all_exceptions = book_exceptions + meta_exceptions + account_exceptions + pos_exceptions
    ok = len(book_exceptions) == 0 and meta_quality not in (STATE_CONFLICTED,) and len(
        [e for e in pos_exceptions if e.get("type") in (
            "shares_x_price_ne_mv", "dual_price_conflict", "weight_mismatch", "upl_mismatch",
        )]
    ) == 0

    # overall quality
    if any(e.get("type") == "dual_price_conflict" or e.get("type") == "shares_x_price_ne_mv" for e in all_exceptions):
        overall = STATE_CONFLICTED
    elif meta_quality == STATE_STALE or any(e.get("type") == "holdings_meta_stale" for e in all_exceptions):
        overall = STATE_STALE
    elif not rows:
        overall = STATE_DATA_UNAVAILABLE
    elif ok:
        overall = STATE_VERIFIED_AS_OF
    else:
        overall = STATE_CONFLICTED

    # suppress ACT NOW for conflicted symbols
    suppress_act_now_symbols = conflicted_symbols[:]

    payload = {
        "gate_version": FINANCIAL_TRUTH_GATE_VERSION,
        "authority": "READ_ONLY_ADVISORY",
        "evaluated_at": now.isoformat(),
        "ok": ok and overall in (STATE_VERIFIED_CURRENT, STATE_VERIFIED_AS_OF),
        "overall_quality": overall,
        "tolerances": {
            "dollar_floor_usd": DOLLAR_FLOOR_TOL,
            "dollar_pct_of_row": DOLLAR_PCT_TOL,
            "weight_pp": WEIGHT_PP_TOL,
            "price_derived_pct": PRICE_DERIVED_PCT_TOL,
        },
        "portfolio": {
            "reported_total_usd": reported_total,
            "total_cash_usd": total_cash,
            "total_long_mv_usd": total_long_mv,
            "derived_portfolio_usd": derived_portfolio,
            "portfolio_value_used_usd": portfolio_value,
            "n_positions": len(pos_rows),
            "n_cash_rows": len(cash_rows),
        },
        "accounts": account_totals,
        "meta": field_meta(
            value={"as_of": meta_as_of, "updated_at": meta_updated},
            source="holdings.json",
            source_as_of=meta_as_of,
            ingested_at=meta_updated,
            quality=meta_quality,
            now=now,
        ),
        "positions": position_results,
        "exceptions": all_exceptions,
        "exception_count": len(all_exceptions),
        "conflicted_symbols": conflicted_symbols,
        "suppress_act_now_symbols": suppress_act_now_symbols,
        "non_actionable_position_count": len(non_actionable),
        "book_invariants": {
            "cash_plus_mv_eq_reported_total": not any(
                e.get("type") == "portfolio_ne_cash_plus_mv" for e in book_exceptions
            ),
            "sum_accounts_eq_derived": not any(
                e.get("type") == "sum_accounts_ne_portfolio" for e in book_exceptions
            ),
        },
    }
    raw = json.dumps(
        {k: payload[k] for k in (
            "gate_version", "portfolio", "exception_count", "conflicted_symbols", "overall_quality",
        )},
        sort_keys=True, default=str,
    )
    payload["gate_hash"] = hashlib.sha256(raw.encode()).hexdigest()
    return payload


def attach_gate_to_capital_plan(
    plan: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, Any]:
    """Attach gate summary; mark decisions non-actionable when symbol conflicted."""
    out = dict(plan)
    suppress = set(gate.get("suppress_act_now_symbols") or [])
    decisions = []
    for d in out.get("position_decisions") or []:
        if not isinstance(d, dict):
            continue
        dd = dict(d)
        sym = str(dd.get("symbol") or "").upper()
        if sym in suppress:
            dd["financial_truth_quality"] = STATE_CONFLICTED
            dd["actionable"] = False
            dd["act_now_suppressed"] = True
            dd["act_now_suppress_reason"] = "financial_truth_conflict"
            # do not strip delta — surface with explicit quality
        else:
            dd.setdefault("financial_truth_quality", gate.get("overall_quality"))
            dd.setdefault("actionable", gate.get("overall_quality") in (
                STATE_VERIFIED_CURRENT, STATE_VERIFIED_AS_OF,
            ))
        decisions.append(dd)
    out["position_decisions"] = decisions
    out["financial_truth_gate"] = {
        "gate_version": gate.get("gate_version"),
        "ok": gate.get("ok"),
        "overall_quality": gate.get("overall_quality"),
        "exception_count": gate.get("exception_count"),
        "conflicted_symbols": gate.get("conflicted_symbols"),
        "suppress_act_now_symbols": gate.get("suppress_act_now_symbols"),
        "portfolio": gate.get("portfolio"),
        "book_invariants": gate.get("book_invariants"),
        "meta_quality": (gate.get("meta") or {}).get("quality"),
        "gate_hash": gate.get("gate_hash"),
        "authority": "READ_ONLY_ADVISORY",
    }
    # Soft book-level flag when earmark equals full cash (semantic smell from Phase 0)
    earmark = _opt_fnum(out.get("cash_earmarked_redeploy_usd"))
    cash = _opt_fnum(out.get("cash_total_usd"))
    if earmark is not None and cash is not None and cash > 0 and abs(earmark - cash) <= dollar_tol(cash):
        out["financial_truth_gate"]["earmark_eq_full_cash"] = True
        out["financial_truth_gate"]["earmark_semantic_warning"] = (
            "cash_earmarked_redeploy_usd equals cash_total — earmark may be over-labeled"
        )
    return out


def run_gate_from_holdings_doc(
    holdings_doc: Optional[dict[str, Any]],
    *,
    plan: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Convenience: evaluate gate and optionally merge into a capital plan."""
    gate = evaluate_holdings_document(holdings_doc, now=now)
    if plan is not None:
        return attach_gate_to_capital_plan(plan, gate)
    return gate
