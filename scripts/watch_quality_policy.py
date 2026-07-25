#!/usr/bin/env python3
"""Deterministic quality admission for the active Watch decision desk.

The research universe may contain thousands of symbols. This module answers a
narrower question before a symbol may carry current entry mechanics:

    Is the instrument suitable for governed swing/position research?

Analyst ratings, social buzz, CIO/model opinions and Hermes rank are not
admission evidence. Local, OAuth and paid models may critique an admitted
validated ticket later, but none can waive this result.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = PROJECT_ROOT / "config" / "watch_quality_policy.json"

_DEFAULT_POLICY = {
    "version": "watch-quality-admission-v1",
    "thresholds": {
        "min_price_usd": 5.0,
        "min_float_millions": 20.0,
        "min_market_cap_usd_millions": 500.0,
        "preferred_market_cap_usd_millions": 1000.0,
        "extreme_atr_pct": 10.0,
        "preferred_max_atr_pct": 7.0,
        "extreme_preprofit_ps": 40.0,
        "preferred_max_preprofit_ps": 20.0,
        "event_like_rvol": 2.5,
        "event_like_atr_pct": 5.0,
    },
    "excluded_structure_tokens": ["SCALP", "LOW_FLOAT", "SOCIAL_MOMENTUM"],
}

ADMITTED = "ADMITTED"
RESEARCH_ONLY = "RESEARCH_ONLY"
QUARANTINED = "QUARANTINED"


def load_policy(path: Path = POLICY_PATH) -> dict:
    """Read a versioned policy, failing closed to the committed defaults.

    The defaults intentionally match the committed policy. A malformed or
    missing file never loosens the gate and is surfaced through policy_source.
    """
    try:
        raw = json.loads(path.read_text())
        thresholds = raw.get("thresholds") or {}
        required = set(_DEFAULT_POLICY["thresholds"])
        if not isinstance(thresholds, dict) or required - set(thresholds):
            raise ValueError("missing required quality thresholds")
        tokens = raw.get("excluded_structure_tokens")
        if not isinstance(tokens, list) or not tokens:
            raise ValueError("excluded_structure_tokens must be a non-empty list")
        return {**raw, "policy_source": str(path), "policy_load_ok": True}
    except Exception as exc:
        return {
            **_DEFAULT_POLICY,
            "policy_source": "embedded fail-closed defaults",
            "policy_load_ok": False,
            "policy_error": f"{type(exc).__name__}: {str(exc)[:120]}",
        }


POLICY = load_policy()
POLICY_VERSION = str(POLICY.get("version") or _DEFAULT_POLICY["version"])
THRESHOLDS = POLICY["thresholds"]
EXCLUDED_STRUCTURE_TOKENS = tuple(
    str(token).upper() for token in POLICY.get("excluded_structure_tokens") or []
)

MIN_PRICE = float(THRESHOLDS["min_price_usd"])
MIN_FLOAT_M = float(THRESHOLDS["min_float_millions"])
MIN_MARKET_CAP_M = float(THRESHOLDS["min_market_cap_usd_millions"])
PREFERRED_MARKET_CAP_M = float(THRESHOLDS["preferred_market_cap_usd_millions"])
EXTREME_ATR_PCT = float(THRESHOLDS["extreme_atr_pct"])
HIGH_ATR_PCT = float(THRESHOLDS["preferred_max_atr_pct"])
EXTREME_PS = float(THRESHOLDS["extreme_preprofit_ps"])
HIGH_PS = float(THRESHOLDS["preferred_max_preprofit_ps"])
EVENT_LIKE_RVOL = float(THRESHOLDS["event_like_rvol"])
EVENT_LIKE_ATR_PCT = float(THRESHOLDS["event_like_atr_pct"])


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
    """Return ADMITTED, RESEARCH_ONLY or QUARANTINED with exact reasons.

    ADMITTED only means this quality layer passed. Arithmetic, event, timing,
    risk, independent-review and operator-release gates still apply.
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

    if any(token in structure for token in EXCLUDED_STRUCTURE_TOKENS):
        hard.append(f"structure {structure} is outside the governed non-scalping Watch mandate")

    if instrument_class == "operating_company":
        if price is None:
            hard.append("current price unavailable")
        elif price < MIN_PRICE:
            hard.append(f"price ${price:.2f} is below the ${MIN_PRICE:.2f} quality floor")

        if float_m is not None and float_m < MIN_FLOAT_M:
            hard.append(f"float {float_m:.1f}M is below the {MIN_FLOAT_M:.0f}M low-float exclusion")
        elif float_m is None and (
            price is None or price < 10
            or (market_cap_m is not None and market_cap_m < PREFERRED_MARKET_CAP_M)
        ):
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

    if (rvol is not None and rvol > EVENT_LIKE_RVOL
            and atr_pct is not None and atr_pct > EVENT_LIKE_ATR_PCT):
        warnings.append(f"event-like volume/volatility combination (RVOL {rvol:.2f}x, ATR {atr_pct:.1f}%)")

    try:
        import deterministic_thesis as thesis_engine
        thesis = thesis_engine.evaluate(facts, facts.get("instrument_type"))
    except Exception as exc:
        thesis = {
            "thesis_state": "INSUFFICIENT_EVIDENCE",
            "error": f"{type(exc).__name__}: {str(exc)[:120]}",
        }
    thesis_state = str(thesis.get("thesis_state") or "INSUFFICIENT_EVIDENCE").upper()
    if thesis_state == "FUNDAMENTALLY_UNATTRACTIVE":
        hard.append("deterministic long-term thesis is FUNDAMENTALLY_UNATTRACTIVE")
    elif thesis_state == "INSUFFICIENT_EVIDENCE":
        warnings.append("deterministic fundamental evidence is insufficient")
    elif thesis_state == "NEUTRAL":
        warnings.append("deterministic long-term thesis is neutral")

    if ps is not None and (profit_margin is None or profit_margin <= 0):
        if ps > EXTREME_PS:
            hard.append(f"P/S {ps:.1f} exceeds the {EXTREME_PS:.0f}x pre-profit quality ceiling")
        elif ps > HIGH_PS:
            warnings.append(f"P/S {ps:.1f} exceeds the preferred {HIGH_PS:.0f}x pre-profit tier")

    if freshness in {"FAILED", "STALE"}:
        hard.append(f"technical snapshot is {freshness}")
    elif freshness not in {"CURRENT", "PARTIAL"}:
        warnings.append(f"technical freshness is {freshness}")

    management_only = held and bool(hard or warnings)
    state = QUARANTINED if hard else RESEARCH_ONLY if warnings else ADMITTED
    new_entry_allowed = state == ADMITTED and not management_only
    if management_only:
        reasons.append("existing holding remains visible for management only; quality issues block a new add")
    reasons.extend(hard)
    reasons.extend(warnings)

    return {
        "policy_version": POLICY_VERSION,
        "policy_source": POLICY.get("policy_source"),
        "policy_load_ok": POLICY.get("policy_load_ok"),
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
        "thresholds_used": THRESHOLDS,
        "authority": "deterministic admission only; models cannot override",
    }
