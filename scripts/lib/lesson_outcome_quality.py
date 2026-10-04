"""Outcome quality checks for lesson evidence (Policy Review P2, operator-approved 2026-10-03).

A lesson may only reach the operator queue on settled outcomes that are real market
results. 2026-10-03: the only outcome-backed lessons on the queue ("TRIM on SCHD held
inconsistently ... −22% to −36%") rested on horizon prices of $18.49–$18.70 for a fund
that ticker_prices records at $33.98–$34.34 on the same dates; the rows the resolver
read were later overwritten. These checks would have refused them.

Pure: callers inject ``price_on(symbol, date)`` (close on or before ``date``) and
``daily_vol(symbol)`` (stdev of daily returns). A check whose lookup is unavailable
fails closed as UNVERIFIABLE; it never passes by default.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Callable, Iterable, Optional

SCHEMA = "LessonOutcomeQuality@v1"
MIN_INDEPENDENT_OUTCOMES = 3
PRICE_BASIS_TOLERANCE = 0.05
SPLIT_RATIOS = (2.0, 3.0, 4.0, 5.0, 10.0, 0.5, 1 / 3, 0.25, 0.2, 0.1)
SPLIT_RATIO_TOLERANCE = 0.03
SPLIT_MOVE_FLOOR = 0.30
VOL_SIGMA_LIMIT = 6.0
MIN_DAILY_VOL = 0.005

PriceOn = Callable[[str, str], Optional[float]]
DailyVol = Callable[[str], Optional[float]]


def _f(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _sessions(start: str, end: str) -> int:
    try:
        a, b = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end)[:10])
    except ValueError:
        return 1
    days = max(1, (b - a).days)
    return max(1, round(days * 5 / 7))


def realized(outcome: dict[str, Any]) -> dict[str, Any]:
    rs = outcome.get("realized_state") if isinstance(outcome.get("realized_state"), dict) else {}
    return {**outcome, **rs}


def check_outcome(outcome: dict[str, Any], *, price_on: Optional[PriceOn] = None,
                  daily_vol: Optional[DailyVol] = None) -> dict[str, Any]:
    """Quality verdict for one settled outcome row (outcome_observations shape)."""
    r = realized(outcome)
    sym = str(r.get("symbol") or "").upper()
    p0, p1 = _f(r.get("price_at_decision")), _f(r.get("price_at_horizon"))
    d0, d1 = str(r.get("decision_price_date") or ""), str(r.get("horizon_price_date") or "")
    reasons: list[str] = []
    if not sym or p0 is None or p1 is None or p0 <= 0 or p1 <= 0 or not d0 or not d1:
        return {"schema": SCHEMA, "ok": False, "outcome_id": r.get("outcome_id"),
                "reasons": ["not_a_market_result: no priced decision and horizon"]}
    move = p1 / p0 - 1.0

    # 1. Price basis: the recorded prices must still match the price store.
    if price_on is None:
        reasons.append("unverifiable: no price store to re-check the recorded prices")
    else:
        for label, recorded, day in (("decision", p0, d0), ("horizon", p1, d1)):
            current = _f(price_on(sym, day))
            if current is None or current <= 0:
                reasons.append(f"unverifiable: no stored {label} price for {sym} on {day}")
            elif abs(recorded - current) / current > PRICE_BASIS_TOLERANCE:
                reasons.append(f"price_basis_mismatch: {label} {recorded:.2f} recorded vs {current:.2f} stored on {day}")

    # 2. Split / corporate-action shape: a big jump at a split-like ratio.
    ratio = p1 / p0
    if abs(move) >= SPLIT_MOVE_FLOOR and any(abs(ratio / k - 1) <= SPLIT_RATIO_TOLERANCE for k in SPLIT_RATIOS):
        reasons.append(f"split_like_jump: ratio {ratio:.3f} over {d0}..{d1} without an adjustment")

    # 3. Plausibility against the symbol's own volatility.
    vol = _f(daily_vol(sym)) if daily_vol else None
    if vol is None:
        if daily_vol is not None:
            reasons.append(f"unverifiable: no volatility history for {sym}")
    else:
        sigma = max(vol, MIN_DAILY_VOL) * math.sqrt(_sessions(d0, d1))
        if abs(move) > VOL_SIGMA_LIMIT * sigma:
            reasons.append(f"implausible_move: {move:+.1%} is {abs(move) / sigma:.1f} sigma for {sym}")

    return {"schema": SCHEMA, "ok": not reasons, "outcome_id": r.get("outcome_id"), "symbol": sym,
            "move": round(move, 6), "decision_date": d0[:10], "reasons": reasons}


def independent_quality_outcomes(outcomes: Iterable[dict[str, Any]], *, price_on: Optional[PriceOn] = None,
                                 daily_vol: Optional[DailyVol] = None) -> dict[str, Any]:
    """Quality-passing outcomes, one per decision (distinct decision date and checkpoint)."""
    passed: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    for o in outcomes:
        verdict = check_outcome(o, price_on=price_on, daily_vol=daily_vol)
        if not verdict["ok"]:
            rejected.append(verdict)
            continue
        key = verdict["decision_date"]
        if key not in passed:
            passed[key] = {**verdict, "change_pct": round(verdict["move"] * 100, 4)}
    return {"independent": list(passed.values()), "rejected": rejected}


def db_lookups(query: Callable[..., Any]) -> tuple[PriceOn, DailyVol]:
    """price_on / daily_vol backed by ticker_prices through a ``_db_query``-style callable."""
    price_cache: dict[tuple[str, str], Optional[float]] = {}
    vol_cache: dict[str, Optional[float]] = {}

    def price_on(symbol: str, day: str) -> Optional[float]:
        key = (symbol, str(day)[:10])
        if key not in price_cache:
            row = query("SELECT close_price FROM ticker_prices WHERE symbol=%s AND price_date<=%s "
                        "ORDER BY price_date DESC, created_at DESC LIMIT 1", key, fetch="one")
            price_cache[key] = _f((row or {}).get("close_price")) if isinstance(row, dict) else None
        return price_cache[key]

    def daily_vol(symbol: str) -> Optional[float]:
        if symbol not in vol_cache:
            rows = query("SELECT close_price FROM ticker_prices WHERE symbol=%s "
                         "ORDER BY price_date DESC LIMIT 61", (symbol,), fetch="all") or []
            closes = [c for c in (_f(r.get("close_price")) for r in rows) if c and c > 0][::-1]
            rets = [b / a - 1 for a, b in zip(closes, closes[1:])]
            if len(rets) < 10:
                vol_cache[symbol] = None
            else:
                mean = sum(rets) / len(rets)
                vol_cache[symbol] = math.sqrt(sum((x - mean) ** 2 for x in rets) / (len(rets) - 1))
        return vol_cache[symbol]

    return price_on, daily_vol


def default_lookups() -> tuple[Optional[PriceOn], Optional[DailyVol]]:
    """ticker_prices lookups via api_v2._db_query when a DB is reachable, else (None, None)."""
    try:
        import api_v2 as _v2  # type: ignore
    except Exception:  # noqa: BLE001
        return None, None
    return db_lookups(_v2._db_query)
