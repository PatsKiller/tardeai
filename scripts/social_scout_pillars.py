#!/usr/bin/env python3
"""social_scout_pillars.py — P0-1: deterministic 5-pillar Social Scout scoring.

A Social Scout is an OPERATOR-AWARENESS state, not an execution state. When a social-discovery
candidate is not yet validation-ready or momentum_scalp/GO-ready, but satisfies at least TWO of the
five defined pillars, TradeAI surfaces it to the operator with a distinct "Social Scout" pill so the
operator understands: this is interesting, it is not quite there yet, it is NOT a GO, it is NOT
validation-fast-path eligible, and it is NOT a standard momentum_scalp trade.

The five pillars:
  1. social_velocity        — strong mention count, source diversity, score, or unusual acceleration.
  2. market_confirmation    — RVOL / volume / gap / price movement confirms the social attention.
  3. catalyst_evidence      — a verified (non-rumor) catalyst (news/filing/event/contract/FDA/insider).
  4. structure_tradeability — float/price/liquidity profile is interpretable; no missing critical data;
                              no obvious halt / offering / reverse-split risk.
  5. strategy_risk_fit      — plausibly maps to a route / watchlist / scout / manual-review lane with a
                              coherent reason; not blocked by hard constraints.

HARD INVARIANTS (this module can NEVER assert otherwise):
  * A Social Scout is ALWAYS not_tradeable and not_validation_ready. Pillar count alone never unlocks
    GO, validation submit, strategy-signal creation, or live trading.
  * 0/5 or 1/5 → no Social Scout pill (operator_pill is None).
  * 2/5, 3/5, 4/5 → Social Scout pill appears.
  * 5/5 does NOT mean GO. Whether a 5/5 candidate is actionable is decided ONLY by the existing route
    policy + deterministic gates (see social_route_policy / validation fast path), never here.

This function is pure and deterministic. LLMs / social sentiment remain advisory inputs only.

Finviz source → pillar mapping (P0-7) — which source feeds which pillar:
  * Finviz RVOL / gap / change / volume          → market_confirmation
  * Finviz price / float / spread / halt / offering / reverse-split risk → structure_tradeability
  * Finviz price / float / RVOL / gap + strategy boundaries → strategy_risk_fit
  * News / catalyst fields (Finviz headlines, SEC, RAG) → catalyst_evidence
  * Social source mention velocity / source diversity   → social_velocity  (NOT Finviz)
So a PURE Finviz candidate can reach 2-4 pillars but can NEVER satisfy social_velocity on its own;
a Finviz + social + verified-catalyst candidate can reach 5/5. 5/5 is still NOT auto-GO — GO is
decided only by social_route_policy + the deterministic gates.
"""
from __future__ import annotations

# Boundary constants are imported from the route policy so the two stay in lock-step (single source of
# truth). route_social_candidate imports THIS module lazily (inside the function), so importing the
# route policy at module load here does not create a circular import.
from social_route_policy import (  # noqa: E402
    catalyst_is_verified,
    SCALP_MAX_FLOAT_M,
    SCOUT_MAX_PRICE,
    _PORTFOLIO_TAGS,
)

PILLARS = ("social_velocity", "market_confirmation", "catalyst_evidence",
           "structure_tradeability", "strategy_risk_fit")

OPERATOR_COLOR_TOKEN = "socialScout"      # distinct, non-GO color (see UI index.css --social-scout)
OPERATOR_SUBTITLE = "Not quite there yet"
SCOUT_STATUS = "SOCIAL_SCOUT"
NO_SCOUT_STATUS = "NONE"
SCOUT_MIN_PILLARS = 2                      # >= 2 of 5 surfaces a Social Scout pill

# Pillar thresholds (deliberately lighter than the momentum_scalp GO gates — a Scout is "interesting,
# not there yet", so confirmation here is weaker than the tradeable scalp boundaries).
VELOCITY_MIN_MENTIONS = 8
VELOCITY_MIN_SOURCES = 2
VELOCITY_MIN_SCORE = 25
CONFIRM_MIN_RVOL = 2.0
CONFIRM_MIN_GAP_PCT = 3.0
CONFIRM_MIN_CHANGE_PCT = 5.0

# Structural disqualifiers — any of these in candidate/catalyst text fails structure_tradeability.
_STRUCTURE_RISK_KEYWORDS = (
    "halt", "trading halt", "halted", "offering", "dilution", "atm offering", "shelf offering",
    "reverse split", "reverse-split", "reverse stock split", "bankruptcy", "chapter 11",
    "delisting", "delist", "going concern", "no bid",
)

# Reason codes (met pillars) — SCOUT_<PILLAR>. Operator-facing, stable strings.
_MET_CODE = {
    "social_velocity": "SCOUT_SOCIAL_VELOCITY",
    "market_confirmation": "SCOUT_MARKET_CONFIRMATION",
    "catalyst_evidence": "SCOUT_CATALYST_EVIDENCE",
    "structure_tradeability": "SCOUT_STRUCTURE_TRADEABILITY",
    "strategy_risk_fit": "SCOUT_STRATEGY_RISK_FIT",
}
# Reason codes for the critical missing pillars (drive operator tooltips).
_MISSING_CODE = {
    "catalyst_evidence": "NEEDS_CATALYST",
    "market_confirmation": "NEEDS_MARKET_CONFIRMATION",
    "structure_tradeability": "NEEDS_TRADEABILITY_CHECK",
}
_TOOLTIP = {
    "NEEDS_CATALYST": "Needs catalyst verification",
    "NEEDS_MARKET_CONFIRMATION": "Needs market confirmation",
    "NEEDS_TRADEABILITY_CHECK": "Needs tradeability check",
}


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _distinct_sources(candidate: dict) -> int:
    srcs = candidate.get("sources") or candidate.get("source_list") or []
    if isinstance(srcs, str):
        srcs = [srcs]
    return len({str(s).strip().lower() for s in srcs if str(s).strip()})


def _risk_text(candidate: dict, catalyst_enrichment: dict) -> str:
    return " ".join(str(x or "").lower() for x in (
        candidate.get("sample_content"),
        catalyst_enrichment.get("catalyst"),
        catalyst_enrichment.get("catalyst_source"),
        catalyst_enrichment.get("structure_risk"),
    ))


def _pillar_social_velocity(candidate: dict, finviz: dict) -> bool:
    if (_num(candidate.get("mention_count")) or 0) >= VELOCITY_MIN_MENTIONS:
        return True
    if _distinct_sources(candidate) >= VELOCITY_MIN_SOURCES:
        return True
    if (_num(candidate.get("score")) or 0) >= VELOCITY_MIN_SCORE:
        return True
    if candidate.get("acceleration") or candidate.get("unusual_acceleration"):
        return True
    return False


def _pillar_market_confirmation(finviz: dict) -> bool:
    rvol = _num(finviz.get("rvol"))
    if rvol is None:
        rvol = _num(finviz.get("relative_volume"))
    gap = _num(finviz.get("gap_pct"))
    change = _num(finviz.get("change_pct"))
    if rvol is not None and rvol >= CONFIRM_MIN_RVOL:
        return True
    if gap is not None and abs(gap) >= CONFIRM_MIN_GAP_PCT:
        return True
    if change is not None and abs(change) >= CONFIRM_MIN_CHANGE_PCT:
        return True
    return False


def _pillar_catalyst_evidence(catalyst_enrichment: dict) -> bool:
    # A verified news/filing/event catalyst OR a recent, relevant SEC/Form 4 open-market insider BUY
    # satisfies catalyst_evidence. SEC/Form 4 is supporting context only — it contributes this pillar
    # when recent + relevant, but (like every other pillar) NEVER creates GO on its own.
    if catalyst_is_verified(catalyst_enrichment):
        return True
    try:
        from sec_form4_source_maturity import sec_form4_catalyst_evidence
        return bool(sec_form4_catalyst_evidence(catalyst_enrichment))
    except Exception:
        return False


def _pillar_structure_tradeability(candidate: dict, finviz: dict, catalyst_enrichment: dict) -> bool:
    price = _num(finviz.get("price"))
    float_m = _num(finviz.get("float_m"))
    if price is None or price <= 0 or float_m is None:   # missing critical data → not interpretable
        return False
    if any(kw in _risk_text(candidate, catalyst_enrichment) for kw in _STRUCTURE_RISK_KEYWORDS):
        return False
    if finviz.get("is_halted") or finviz.get("halted"):
        return False
    return True


def _pillar_strategy_risk_fit(candidate: dict, finviz: dict) -> bool:
    # Coherent mapping to a scout/scalp/manual-review lane: interpretable price within the scout
    # ceiling, a known float, some volume signal, and not a portfolio/income name.
    price = _num(finviz.get("price"))
    float_m = _num(finviz.get("float_m"))
    rvol = _num(finviz.get("rvol")) if finviz.get("rvol") is not None else _num(finviz.get("relative_volume"))
    tags = [str(t).lower() for t in (candidate.get("strategy_tags") or [])]
    if any(t in _PORTFOLIO_TAGS for t in tags):
        return False
    if price is None or float_m is None or rvol is None:
        return False
    return 0 < price <= SCOUT_MAX_PRICE


def evaluate_social_scout_pillars(candidate: dict, finviz_data: dict,
                                  catalyst_enrichment: dict) -> dict:
    """Evaluate the 5 Social Scout pillars for one social candidate. Pure / deterministic.

    Returns the canonical Social Scout dict. Always not_tradeable + not_validation_ready — a Scout is
    awareness-only. The route policy decides the LARGE-FLOAT label and whether a 5/5 candidate is
    actually actionable (GO) through its own gates; this module never makes that call.
    """
    candidate = candidate or {}
    finviz = finviz_data or {}
    ce = catalyst_enrichment or {}

    met_map = {
        "social_velocity": _pillar_social_velocity(candidate, finviz),
        "market_confirmation": _pillar_market_confirmation(finviz),
        "catalyst_evidence": _pillar_catalyst_evidence(ce),
        "structure_tradeability": _pillar_structure_tradeability(candidate, finviz, ce),
        "strategy_risk_fit": _pillar_strategy_risk_fit(candidate, finviz),
    }
    pillars_met = [p for p in PILLARS if met_map[p]]
    pillars_missing = [p for p in PILLARS if not met_map[p]]
    count = len(pillars_met)
    is_scout = count >= SCOUT_MIN_PILLARS

    reason_codes = [_MET_CODE[p] for p in pillars_met]
    missing_reason_codes = [_MISSING_CODE[p] for p in pillars_missing if p in _MISSING_CODE]
    tooltip_hints = [_TOOLTIP[c] for c in missing_reason_codes]

    return {
        "pillar_count": count,
        "pillars_met": pillars_met,
        "pillars_missing": pillars_missing,
        "scout_status": SCOUT_STATUS if is_scout else NO_SCOUT_STATUS,
        "operator_pill": f"SOCIAL SCOUT · {count}/5" if is_scout else None,
        "operator_subtitle": OPERATOR_SUBTITLE if is_scout else None,
        "operator_color_token": OPERATOR_COLOR_TOKEN if is_scout else None,
        "operator_tooltip_hints": tooltip_hints,
        # HARD invariants — a Scout surface is never tradeable / never validation-ready.
        "not_validation_ready": True,
        "not_tradeable": True,
        "reason_codes": reason_codes,
        "missing_reason_codes": missing_reason_codes,
    }


if __name__ == "__main__":
    import json
    demo = evaluate_social_scout_pillars(
        {"symbol": "SCOUT", "mention_count": 40, "sources": ["reddit", "stocktwits"]},
        {"price": 6.0, "rvol": 4.0, "float_m": 12.0, "gap_pct": 1.0, "change_pct": 2.0},
        {})  # no verified catalyst → catalyst + maybe others missing
    print(json.dumps(demo, indent=2))
