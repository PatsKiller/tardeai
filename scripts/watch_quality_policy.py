#!/usr/bin/env python3
"""watch_quality_policy.py — deterministic admission gate for the active Watch desk.

The Watch universe may contain thousands of research candidates.  This module
answers a narrower question before a candidate may present current entry
mechanics or become proposal-eligible:

    Is this instrument suitable for the governed, non-scalping Watch workflow?

It is deliberately model-free and pure.  Analyst ratings, social buzz, CIO
verdicts, model opinions and Hermes rank are not admission evidence.  Local,
OAuth and paid models may critique an admitted ticket later, but none can
waive a rejection here.

The policy does not delete research.  Names that fail are retained as
RESEARCH_ONLY or QUARANTINED with explicit reasons.  Existing holdings remain
visible for management, but a held-name exemption never authorizes a new add.
"""
from __future__ import annotations

import math
from typing import Any

POLICY_VERSION = "watch-quality-admission-v1"

ADMITTED = "ADMITTED"
RESEARCH_ONLY = "RESEARCH_ONLY"
QUARANTINED = "QUARANTINED"

MIN_PRICE = 5.0
MIN_FLOAT_M = 20.0
MIN_MARKET_CAP_M = 500.0
PREFERRED_MARKET_CAP_M = 1_000.0
EXTREME_ATR_PCT = 10.0
HIGH_ATR_PCT = 7.0
EXTREME_PS = 40.0
HIGH_PS = 20.0


def _num(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _held(ownership: Any) -> bool:
    if ownership is None:
        return False
    if isinstance(ownership, dict):
        return bool(ownership.get("held") or ownership.get("is_held"))
    return bool(getattr(ownership, "held", False))


def _technical_freshness(snapshot: dict | None) -> str:
    return str((snapshot or {}).get("overall_freshness") or "UNKNOWN").upper()


def _structure_name(ticket: dict | None) -> str:
    return str((ticket or {}).get("structure") or "").upper()


def _instrument_class(facts: dict) -> str:
    quote = str(facts.get("quote_type") or "").upper()
    instrument = str(facts.get("instrument_type") or "").upper()
    if quote in {"ETF", "MUTUALFUND"} or instrument in {"ETF", "FUND", "MUTUAL_FUND", "CEF"}:
        return "fund"
    return "operating_company"


def evaluate_admission(
    facts: dict | None,
    *,
    technical_snapshot: dict | None = None,
    ticket: dict | None = None,
    family: str | None = None,
    ownership: Any = None,
) -> dict:
    """Return the deterministic Watch admission result.

    QUARANTINED is a hard new-entry refusal. RESEARCH_ONLY preserves the name
    for evidence gathering but withholds current actionable mechanics.
    ADMITTED only means the instrument clears this quality layer; all normal
    event, timing, arithmetic, risk and independent-review gates still apply.
    """
    facts = facts or {}
    fundamentals = facts.get("fundamentals") or {}
    held = _held(ownership)
    reasons: list[str] = []
    warnings: list[str] = []
    hard: list[str] = []

    price = _num(facts.get("live_price")) or _num(facts.get("enriched_price"))
    float_m = _num(facts.get("float_m")) or _num(fundamentals.get("shares_outstanding_m"))
    market_cap_m = _num(fundamentals.get("market_cap_usd_millions"))
    atr = _num(facts.get("atr"))
    atr_pct = (100.0 * atr / price) if atr is not None and price not in (None, 0) else None
    rvol = _num(facts.get("rvol"))
    ps = _num(fundamentals.get("ps"))
    profit_margin = _num(fundamentals.get("profit_margin_pct"))
    freshness = _technical_freshness(technical_snapshot)
    structure = _structure_name(ticket)
    instrument_class = _instrument_class(facts)

    # Strategy-family exclusion is categorical, not a score.  The governed
    # Watch desk is for swing/position research, never social/momentum scalps.
    if any(token in structure for token in ("SCALP", "LOW_FLOAT", "SOCIAL_MOMENTUM")):
        hard.append(f"structure {structure} is outside the governed non-scalping Watch mandate")

    if instrument_class == "operating_company":
        if price is None:
            hard.append("current price unavailable")
        elif price < MIN_PRICE:
            hard.append(f"price ${price:.2f} is below the ${MIN_PRICE:.2f} quality floor")

        if float_m is not None and float_m < MIN_FLOAT_M:
            hard.append(f"float {float_m:.1f}M is below the {MIN_FLOAT_M:.0f}M low-float exclusion")
        elif float_m is None and (price is None or price < 10 or (market_cap_m is not None and market_cap_m < PREFERRED_MARKET_CAP_M)):
            warnings.append("float is unavailable for a lower-priced or smaller company")

        if market_cap_m is not None and market_cap_m < MIN_MARKET_CAP_M:
            hard.append(f"market cap ${market_cap_m:.0f}M is below the ${MIN_MARKET_CAP_M:.0f}M quality floor")
        elif market_cap_m is None:
            warnings.append("market capitalization unavailable")
        elif market_cap_m < PREFERRED_MARKET_CAP_M:
            warnings.append(f"market cap ${market_cap_m:.0f}M is below the preferred ${PREFERRED_MARKET_CAP_M:.0f}M tier")

    if atr_pct is None:
        warnings.append("ATR percentage unavailable")
    elif atr_pct > EXTREME_ATR_PCT:
        hard.append(f"ATR {atr_pct:.1f}% exceeds the {EXTREME_ATR_PCT:.0f}% extreme-volatility ceiling")
    elif atr_pct > HIGH_ATR_PCT:
        warnings.append(f"ATR {atr_pct:.1f}% exceeds the preferred {HIGH_ATR_PCT:.0f}% volatility tier")

    if rvol is not None and rvol > 2.5 and atr_pct is not None and atr_pct > 5:
        warnings.append(f"event-like volume/volatility combination (RVOL {rvol:.2f}x, ATR {atr_pct:.1f}%)")

    # Reuse the deterministic thesis engine; this is raw-fact arithmetic and
    # fixed rules, not an LLM opinion.
    try:
        import deterministic_thesis as thesis_engine
        thesis = thesis_engine.evaluate(facts, facts.get("instrument_type"))
    except Exception as exc:  # fail closed to research, never fabricate quality
        thesis = {"thesis_state": "INSUFFICIENT_EVIDENCE", "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    thesis_state = str(thesis.get("thesis_state") or "INSUFFICIENT_EVIDENCE").upper()
    if thesis_state == "FUNDAMENTALLY_UNATTRACTIVE":
        hard.append("deterministic long-term thesis is FUNDAMENTALLY_UNATTRACTIVE")
    elif thesis_state == "INSUFFICIENT_EVIDENCE":
        warnings.append("deterministic fundamental evidence is insufficient")
    elif thesis_state == "NEUTRAL":
        warnings.append("deterministic long-term thesis is neutral")

    # Rich pre-profit names are not admitted merely because price momentum is
    # strong.  The threshold is intentionally transparent and reviewable.
    if ps is not None and (profit_margin is None or profit_margin <= 0):
        if ps > EXTREME_PS:
            hard.append(f"P/S {ps:.1f} exceeds the {EXTREME_PS:.0f}x pre-profit quality ceiling")
        elif ps > HIGH_PS:
            warnings.append(f"P/S {ps:.1f} exceeds the preferred {HIGH_PS:.0f}x pre-profit tier")

    if freshness in {"FAILED", "STALE"}:
        hard.append(f"technical snapshot is {freshness}")
    elif freshness not in {"CURRENT", "PARTIAL"}:
        warnings.append(f"technical freshness is {freshness}")

    # Existing positions stay on the desk for management even when they would
    # not be admitted as a fresh candidate.  The output remains explicit that
    # no new entry/add is authorized by this exemption.
    management_only = held and bool(hard or warnings)
    if hard:
        state = QUARANTINED
    elif warnings:
        state = RESEARCH_ONLY
    else:
        state = ADMITTED

    new_entry_allowed = state == ADMITTED and not management_only
    if management_only:
        reasons.append("existing holding remains visible for management only; quality issues block a new add")
    reasons.extend(hard)
    reasons.extend(warnings)

    return {
        "policy_version": POLICY_VERSION,
        "state": state,
        "new_entry_allowed": new_entry_allowed,
        "management_only": management_only,
        "family": str(family or "").upper() or None,
        "instrument_class": instrument_class,
        "thesis_state": thesis_state,
        "reasons": reasons,
        "hard_failures": hard,
        "warnings": warnings,
        "facts_used": {
            "price": price,
            "float_m": float_m,
            "market_cap_usd_millions": market_cap_m,
            "atr_pct": round(atr_pct, 2) if atr_pct is not None else None,
            "rvol": rvol,
            "ps": ps,
            "profit_margin_pct": profit_margin,
            "technical_freshness": freshness,
            "structure": structure or None,
        },
        "authority": "deterministic admission only; models cannot override",
    }
