#!/usr/bin/env python3
"""blind_review.py — genuinely independent first-pass model analysis.

THE DEFECT THIS REPLACES
------------------------
`cloud_review._build_prompt` opens with "You are an INDEPENDENT reviewer" and
then hands the model the local verdict verbatim, asking whether it is sound. Two
things follow, and the second is worse than the first:

1. ANCHORING. Both lanes receive the same prior conclusion, so agreement between
   them is correlated by construction. "✓ 2 models agree" reports the strength
   of the anchor, not the weight of the evidence.

2. GRAMMAR. The verdict vocabulary is AGREE / CAUTION / DISAGREE. Those are
   opinions ABOUT someone else's answer. There is no token in that vocabulary
   for "constructive long term, extended short term, wait for a pullback." The
   reviewer literally cannot express an independent view, only rate one.

(2) is why raising the prompt's quality would not have fixed this. A blind pass
needs its own output shape, so this module carries one.

WHAT THIS MODULE DOES
---------------------
Pass A  — each model sees the SAME facts and NO verdict from anyone. Returns a
          decision packet of its own.
Pass B  — the local committee produces the same structure, separately.
Pass C  — an arbiter sees all blind outputs and reconciles, per dimension.

Agreement is measured PER DIMENSION. A split on timing is not a split on company
quality, and collapsing them loses the most useful thing disagreement tells you.

The anchored path is not deleted — it remains valid as a REVIEW of a known
verdict. It is renamed so it can never again be displayed as independence.

PURE: builds prompts and reconciles results. Callers own the network.
"""
from __future__ import annotations

import json
from typing import Any

from decision_packet import (
    DIRECTIONS, EVENT_STATES, THESIS_STATES, TIMING_STATES,
)

# What the anchored path must be called wherever it is surfaced.
ANCHORED_LABEL = "VERDICT REVIEW — PRIOR VERDICT PROVIDED"
BLIND_LABEL = "INDEPENDENT ANALYSIS — BLIND FIRST PASS"

# Dimensions agreement is measured across, separately.
CONSENSUS_DIMENSIONS = ("long_term_thesis", "tactical_timing", "direction",
                        "instrument", "event_risk")

# Keys that must NEVER appear in a blind facts packet. Enforced, not trusted:
# a single stray key silently converts a blind pass back into an anchored one,
# and the resulting badge would claim independence it does not have.
FORBIDDEN_IN_BLIND = frozenset({
    "recommendation", "verdict", "committee_verdict", "cio_verdict",
    "local_output", "confidence", "rationale", "assessment", "consensus",
    "grok_verdict", "chatgpt_verdict", "prior_verdict", "conclusion",
    "cio_recommendation", "final_synthesis", "committee_conclusion",
    "model_verdict", "recommendation_label", "action",
})


class BlindnessViolation(ValueError):
    """A facts packet carrying a prior verdict. Refused rather than sanitised:
    silently stripping it would leave no evidence the caller tried."""


def assert_blind(facts: dict, *, path: str = "") -> None:
    """Recursively refuse any key that would anchor the model."""
    for key, value in (facts or {}).items():
        here = f"{path}.{key}" if path else str(key)
        if str(key).lower() in FORBIDDEN_IN_BLIND:
            raise BlindnessViolation(
                f"facts packet contains {here!r}, which would anchor the model. "
                "A blind pass may contain evidence only — no verdict, no confidence, "
                "no prior conclusion from any source."
            )
        if isinstance(value, dict):
            assert_blind(value, path=here)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    assert_blind(item, path=f"{here}[{i}]")


def build_facts_packet(*, symbol: str, price: dict, technicals: dict,
                       fundamentals: dict, catalysts: list, events: dict,
                       ownership: dict, options_summary: dict | None,
                       data_quality: dict) -> dict:
    """Evidence only. Every model in the blind pass gets this exact object, so
    any disagreement is attributable to reasoning rather than to inputs."""
    packet = {
        "symbol": symbol,
        "price": price,
        "technicals": technicals,
        "fundamentals": fundamentals,
        "catalysts": catalysts,
        "events": events,
        "ownership": ownership,
        "options_summary": options_summary or {},
        "data_quality": data_quality,
    }
    assert_blind(packet)
    return packet


def build_blind_prompt(facts: dict) -> str:
    """No prior verdict, and an output shape that can hold an independent view."""
    assert_blind(facts)
    return (
        "You are an independent equity analyst in a personal PAPER-trading research "
        "system. ADVISORY ONLY — never instruct anyone to place, buy, sell or route an "
        "order, and never state a price, greek or analyst figure that is not in the "
        "facts below.\n\n"
        "You are seeing this symbol cold. No other analyst's conclusion is available to "
        "you, by design. Reach your own view from the evidence.\n\n"
        "FACTS:\n" + json.dumps(facts, indent=2, default=str)[:9000] + "\n\n"
        "Answer these SEPARATELY. They are different questions and a good answer to one "
        "does not imply anything about the others:\n"
        "  1. Would you want to OWN this for 1-5 years?      (thesis, independent of price today)\n"
        "  2. Is TODAY a good entry?                          (timing, independent of quality)\n"
        "  3. Which DIRECTION does the evidence favour, per horizon?\n"
        "  4. Which INSTRUMENT fits — shares, cash-secured put, call spread, or nothing?\n"
        "  5. What EVENT could change this?\n"
        "  6. Is the data fresh enough to act on?\n\n"
        "A company can be excellent AND a poor entry today. Say so when it is true; do "
        "not average the two into a single verdict.\n"
        "Cite the specific fact keys you relied on. If the evidence does not support a "
        "conclusion, say INSUFFICIENT_EVIDENCE rather than guessing.\n\n"
        "Return ONLY this JSON:\n"
        "{\n"
        f'  "long_term_thesis": {{"state": one of {list(THESIS_STATES)}, "confidence": 0.0-1.0,\n'
        '                        "why": [], "what_changes_view": []}},\n'
        f'  "tactical_timing": {{"state": one of {list(TIMING_STATES)}, "confidence": 0.0-1.0,\n'
        '                       "trigger": "", "invalidation": ""}},\n'
        f'  "direction": {{"tactical": one of {list(DIRECTIONS)}, "swing": ..., "long_term": ...}},\n'
        '  "instrument": {"preferred": "", "why": [], "rejected": []},\n'
        f'  "event_risk": {{"impact": one of {list(EVENT_STATES)}, "detail": ""}},\n'
        '  "data_sufficient": true|false,\n'
        '  "evidence_used": [],\n'
        '  "unresolved_questions": []\n'
        "}"
    )


def build_arbiter_prompt(symbol: str, blind_outputs: dict[str, dict]) -> str:
    """The ONLY stage that may see more than one view. Its job is reconciliation,
    which requires the disagreements to still be visible — so they are passed in
    labelled by source rather than pre-merged."""
    return (
        f"You are reconciling several INDEPENDENT analyses of {symbol}. Each analyst "
        "worked blind: none saw another's conclusion.\n\n"
        "ANALYSES:\n" + json.dumps(blind_outputs, indent=2, default=str)[:9000] + "\n\n"
        "Reconcile them DIMENSION BY DIMENSION. Disagreement on timing is not "
        "disagreement on company quality — report each separately and never let one "
        "dimension's split contaminate another.\n"
        "Where they disagree, identify the specific evidence driving the difference. "
        "Preserve the minority view; do not average it away.\n\n"
        "Return ONLY this JSON:\n"
        "{\n"
        '  "by_dimension": {"<dimension>": {"agreement": "UNANIMOUS|MAJORITY|SPLIT",\n'
        '                    "reconciled": "", "minority_view": "", "evidence": []}},\n'
        '  "reconciled_headline": "",\n'
        '  "confidence": 0.0-1.0,\n'
        '  "unresolved_data": []\n'
        "}"
    )


def _dim_value(out: dict, dimension: str) -> str:
    """Pull one dimension's comparable token out of a blind output."""
    if not isinstance(out, dict):
        return "UNKNOWN"
    if dimension == "long_term_thesis":
        return str((out.get("long_term_thesis") or {}).get("state") or "UNKNOWN")
    if dimension == "tactical_timing":
        return str((out.get("tactical_timing") or {}).get("state") or "UNKNOWN")
    if dimension == "direction":
        return str((out.get("direction") or {}).get("tactical") or "UNKNOWN")
    if dimension == "instrument":
        return str((out.get("instrument") or {}).get("preferred") or "UNKNOWN")
    if dimension == "event_risk":
        return str((out.get("event_risk") or {}).get("impact") or "UNKNOWN")
    return "UNKNOWN"


def measure_agreement(blind_outputs: dict[str, dict]) -> dict:
    """Per-dimension agreement. Deterministic — counting is not a model's job.

    Returns per dimension: the vote spread, an agreement level, and the count,
    so the UI can render "THESIS 3/3 · TIMING 1/3" instead of one badge that
    averages a strong consensus with a total split.
    """
    sources = [s for s, o in (blind_outputs or {}).items() if isinstance(o, dict) and o]
    out: dict[str, Any] = {"sources": sources, "n": len(sources), "dimensions": {}}

    for dim in CONSENSUS_DIMENSIONS:
        votes: dict[str, list[str]] = {}
        for src in sources:
            votes.setdefault(_dim_value(blind_outputs[src], dim), []).append(src)
        known = {v: s for v, s in votes.items() if v != "UNKNOWN"}
        n = sum(len(s) for s in known.values())
        top = max(known.values(), key=len) if known else []
        agreement = ("NO_DATA" if not known
                     else "UNANIMOUS" if len(known) == 1 and n > 1
                     else "SINGLE_SOURCE" if n == 1
                     else "MAJORITY" if len(top) > n / 2
                     else "SPLIT")
        out["dimensions"][dim] = {
            "agreement": agreement,
            "votes": {v: sorted(s) for v, s in votes.items()},
            "agreeing": len(top), "of": n,
            "display": f"{len(top)}/{n}" if n else "no data",
        }

    # Any dimension may be unanimous while another is split; there is deliberately
    # no overall score here, because collapsing them is the defect being fixed.
    return out


def consensus_badge(agreement: dict, *, blind: bool) -> dict:
    """What the UI may display. A badge from a non-blind pass MUST say so —
    the old '✓ 2 models' claimed an independence the prompt never delivered."""
    dims = (agreement or {}).get("dimensions") or {}
    return {
        "independence": "BLIND" if blind else "ANCHORED",
        "label": BLIND_LABEL if blind else ANCHORED_LABEL,
        "may_claim_independence": bool(blind),
        "per_dimension": {d: v.get("display") for d, v in dims.items()},
        "detail": {d: v.get("agreement") for d, v in dims.items()},
        "caveat": None if blind else (
            "These models were shown the prior verdict before answering. Their "
            "agreement measures the strength of that anchor, not independent "
            "confirmation."
        ),
    }
