"""Deterministic admission checks for automatic research inputs and outputs."""
from __future__ import annotations

import re
from typing import Any

SCHEMA = "ResearchDataQualityGate@v1"
_ZERO_PE = re.compile(
    r"\b(?:p\s*/\s*e|pe)(?:\s+ratio)?\s*(?:is|of|[:=])?\s*0(?:\.0+)?\b",
    re.IGNORECASE,
)
_ZERO_52W_RANGE = re.compile(
    r"\b52[- ]week\s+(?:range|low\s*/\s*high|high\s*/\s*low)"
    r"[^\n.;]{0,50}?\$?0(?:\.0+)?\s*(?:-|to|through|\u2013|\u2014)\s*\$?0(?:\.0+)?\b",
    re.IGNORECASE,
)

# \u2500\u2500 LLM refusals are not research output \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# 2026-11-07 data-truth audit (defect 8): /api/v2/hermes/subject-intel-map served 159
# "recommendations", dozens of them the model declining \u2014 "**Decline.** This request asks
# for trading signals\u2026", "Active profile is default (non-trading)", "I am Hermes in the
# default profile". A refusal carries no recommendation; storing or serving one as advice
# labels an absence as a signal. The markers below are the shapes the governed lanes
# actually returned (159 rows captured read-only from that route on 2026-11-07).
# Deterministic by design: no model, no score, no threshold.
_MD_NOISE = re.compile(r"[*#_`>~]+")
_WS = re.compile(r"\s+")
_REFUSAL_WORD = re.compile(r"\b(decline|declined|refused|refusal|refusing)\b", re.IGNORECASE)
# The answer opens by declaring which identity it is answering as \u2014 the default,
# non-advisory Hermes profile rather than the governed trading-advisory lane.
_BOUNDARY_DECL = re.compile(
    r"(?:"
    r"\b(?:active|current)\s+(?:hermes\s+)?(?:profile|identity)\s+is\s+(?:the\s+)?default\b"
    r"|\bdefault\s+hermes\s+(?:assistant|profile|non-trading|conducting|\()"
    r"|\bhermes\s+in\s+the\s+default(?:\s+non-trading)?\s+profile\b"
    r"|\b(?:operating|reviewing|working)\s+under\s+the\s+default\s+hermes"
    r"|\bas\s+the\s+default\s+hermes\b"
    r"|\brole:\s*(?:hermes\s+)?default\b"
    r"|\bnot\s+the\s+governed\s+(?:deepseek|trading-advisory)"
    r")",
    re.IGNORECASE,
)
# A short answer whose whole content is "I cannot <do the asked thing>".
_CANNOT_ANSWER = re.compile(
    r"\b(?:cannot|can't|can not|will not|won't|do not|does not|unable to)\s+"
    r"(?:provide|create|generate|produce|assume|switch|act as|adopt|approve|comply|fulfill|supply)\b",
    re.IGNORECASE,
)
_SHORT_ANSWER_CHARS = 900
_HEAD_CHARS = 160
_LEAD_CHARS = 200


def _opening(text: str) -> str:
    """The first sentence (bounded), which is where a model states what it is answering as.

    Bounded on purpose: a real analysis may cite the profile boundary much later (for
    example "the default Hermes profile boundary was applied to the entry/stop part"),
    and that sentence must not reclassify the whole answer as a refusal.
    """
    lead = text[:_LEAD_CHARS]
    for sep in (". ", ".\n", "! ", "? "):
        cut = lead.find(sep)
        if cut > 0:
            return lead[:cut + 1]
    return lead


def refusal_kind(text: Any) -> str | None:
    """``"refused"`` | ``"boundary"`` | ``None`` \u2014 does this text decline instead of answer?

    ``refused``  the model declined outright (refusal wording, or a short cannot-answer).
    ``boundary`` the answer proceeds under the default Hermes profile and says so in its
                 opening sentence, so it is explicitly not the governed advisory answer.

    ``None`` means the text is usable as research output. Only the opening decides: a real
    analysis that merely cites the boundary later (say, a verdict quoting AGENTS.md) stays
    usable, so genuine content is never thrown away.
    """
    t = _WS.sub(" ", _MD_NOISE.sub("", str(text or ""))).strip()
    if not t:
        return None
    head = t[:_HEAD_CHARS]
    opening = _opening(t)
    if _REFUSAL_WORD.search(head):
        return "refused"
    if _BOUNDARY_DECL.search(opening):
        return "boundary"
    if len(t) <= _SHORT_ANSWER_CHARS and _CANNOT_ANSWER.search(opening):
        return "refused"
    return None


def refusal_reason(kind: str | None) -> str:
    """One operator-readable line for a refusal kind. Never blank for a non-None kind."""
    if kind == "refused":
        return "the model declined the request"
    if kind == "boundary":
        return "answered as the default Hermes profile, not the trading-advisory lane"
    return ""


def assess_prompt_context(context: dict[str, Any]) -> dict[str, Any]:
    market = dict(context.get("deterministic_current_data") or {})
    reasons: list[str] = []
    for key in ("price", "atr", "avg_vol_m"):
        value = market.get(key)
        if value is not None:
            try:
                if float(value) <= 0:
                    reasons.append(f"invalid_{key}")
            except (TypeError, ValueError):
                reasons.append(f"non_numeric_{key}")
    high = market.get("week52_high_pct")
    low = market.get("week52_low_pct")
    try:
        if high is not None and low is not None and float(high) == 0 and float(low) == 0:
            reasons.append("invalid_zero_52week_range")
    except (TypeError, ValueError):
        reasons.append("non_numeric_52week_range")
    return {
        "schema": SCHEMA,
        "status": "BLOCK" if reasons else "PASS",
        "reason_codes": sorted(set(reasons)),
        "provider_call_allowed": not reasons,
        "authority": "READ_ONLY_ADVISORY",
    }


def validate_research_output(text: str) -> dict[str, Any]:
    body = str(text or "")
    reasons = []
    if _ZERO_PE.search(body):
        reasons.append("placeholder_zero_pe")
    if _ZERO_52W_RANGE.search(body):
        reasons.append("placeholder_zero_52week_range")
    # A hard refusal carries no research at all, so it is rejected here rather than stored
    # as a thesis: every success-status consumer (subject-intel, outcome grading, dedupe)
    # then stops seeing it. A boundary answer (an evidence review written under the default
    # profile) keeps its analysis and is labelled downstream instead of being discarded.
    if refusal_kind(body) == "refused":
        reasons.append("llm_refusal")
    return {
        "schema": SCHEMA,
        "status": "REJECT" if reasons else "PASS",
        "reason_codes": reasons,
        "accepted": not reasons,
        "instruction": "Use DATA_UNAVAILABLE for missing facts; never convert missing values to zero.",
        "authority": "READ_ONLY_ADVISORY",
    }
