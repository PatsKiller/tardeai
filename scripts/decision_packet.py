#!/usr/bin/env python3
"""decision_packet.py — the multidimensional decision packet.

WHY THIS EXISTS
---------------
The system compressed six independent questions into one word:

    "Is the company good?"          "Is today a good entry?"
    "Which direction?"              "Which instrument?"
    "What event is coming?"         "Is the data fresh?"

...all collapsed to `IGNORE`. That label is unfalsifiable: it cannot be wrong
in a way anyone can point at, because it never said which question it was
answering. BETA (2026-07-20) is the fixture — a company with a $3.9B backlog and
$1.6B cash, up 20% in a month, rendered as `IGNORE` while the packet behind it
was 2.9 days stale.

The states below are deliberately NOT rankable on one axis. There is no
arithmetic that turns this packet back into a single score, and that is the
point: any caller wanting one word must choose WHICH DIMENSION it is about.

OWNERSHIP BOUNDARY (enforced by validate(), not by convention)
--------------------------------------------------------------
Deterministic code owns: prices, freshness, ownership, account capability,
optionability, liquidity, earnings-inside-contract, position size, cash and
share availability, technical levels, all payoff and stop arithmetic, and every
eligibility decision.

Models own: thesis interpretation, qualitative risk, catalyst importance,
scenario analysis, and what evidence would change the view.

A model may not invent a strike, a quote, a greek, a cash requirement, or any
payoff number. Fields carrying those are marked DETERMINISTIC_FIELDS and
validate() refuses a packet whose provenance says a model produced them.

This module is PURE: no network, no database, no clock beyond what is passed in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Dimension A: long-term thesis ─────────────────────────────────────────────
# Answers ONLY "would I want to own this for years?" Never "is today an entry?"
THESIS_STATES = (
    "STRONG_CONVICTION",
    "CONSTRUCTIVE",
    "SPECULATIVE_CONSTRUCTIVE",   # credible thesis, materially unproven — BETA sits here
    "NEUTRAL",
    "DETERIORATING",
    "FUNDAMENTALLY_UNATTRACTIVE",
    "INSUFFICIENT_EVIDENCE",
)

# ── Dimension B: tactical timing ──────────────────────────────────────────────
# Answers ONLY "is there a favourable entry/exit in the next few sessions?"
TIMING_STATES = (
    "READY",
    "STARTER_ONLY",
    "WAIT_FOR_PULLBACK",
    "WAIT_FOR_BREAKOUT",
    "BREAKOUT_CONFIRMATION",
    "EXTENDED",
    "RANGE_BOUND",
    "REVERSAL_WATCH",
    "EVENT_BLOCKED",
    "NO_VALID_SETUP",
)

# ── Dimension C: direction ────────────────────────────────────────────────────
DIRECTIONS = (
    "BULLISH", "MILDLY_BULLISH", "NEUTRAL",
    "MILDLY_BEARISH", "BEARISH", "BINARY_EVENT", "UNRESOLVED",
)

# A horizon is MANDATORY on every direction. "Short" without a horizon is
# ambiguous between "short duration" and "short exposure" — a confusion that can
# invert a position, so the vocabulary makes it unsayable.
HORIZONS = ("tactical", "swing", "long_term")
HORIZON_WINDOWS = {
    "tactical": "1-10 sessions",
    "swing": "2-8 weeks",
    "long_term": "1-5 years",
}

# ── Dimension G: event state ──────────────────────────────────────────────────
EVENT_STATES = ("CLEAR", "CAUTION", "BLOCKED", "UNKNOWN", "STALE", "CONFLICTED")

# ── Dimension H: data quality ─────────────────────────────────────────────────
DATA_STATES = ("FRESH", "PARTIAL", "STALE", "CONFLICTED", "INSUFFICIENT", "PROVIDER_DOWN")

# A packet in one of these states may carry a prior thesis, but only labelled.
NON_ACTIONABLE_DATA = ("STALE", "CONFLICTED", "INSUFFICIENT", "PROVIDER_DOWN")
PRIOR_THESIS_LABEL = "PRIOR THESIS — NOT REVALIDATED"

# ── Structure eligibility ─────────────────────────────────────────────────────
STRUCTURE_STATES = ("ELIGIBLE", "CONDITIONAL", "REJECTED", "NOT_APPLICABLE", "DATA_UNAVAILABLE")

BULLISH_STRUCTURES = (
    "STAGED_SHARES", "FULL_SHARES", "BREAKOUT_ENTRY", "PULLBACK_ENTRY",
    "SUPPORT_BOUNCE_ENTRY", "POST_EVENT_ENTRY",
    "CASH_SECURED_PUT", "LONG_CALL", "CALL_DEBIT_SPREAD", "BULL_PUT_SPREAD",
    "DIAGONAL_CALL", "BUY_WRITE",
)
BEARISH_STRUCTURES = (
    "SHORT_STOCK", "STAGED_SHORT", "FAILED_RALLY_SHORT", "BREAKDOWN_SHORT",
    "LONG_PUT", "PUT_DEBIT_SPREAD", "BEAR_CALL_SPREAD", "INDEX_HEDGE",
)
HELD_STRUCTURES = (
    "HOLD", "ADD", "ADD_ON_PULLBACK", "TRIM", "EXIT",
    "COVERED_CALL", "PROTECTIVE_PUT", "COLLAR", "REPLACE", "NO_ACTION",
)
NEUTRAL_STRUCTURES = ("IRON_CONDOR", "CALENDAR_SPREAD", "NO_TRADE")

ALL_STRUCTURES = BULLISH_STRUCTURES + BEARISH_STRUCTURES + HELD_STRUCTURES + NEUTRAL_STRUCTURES

# Structures not yet governed for execution; may be researched, never proposed.
RESEARCH_ONLY = ("IRON_CONDOR", "CALENDAR_SPREAD", "DIAGONAL_CALL")

# ── Retiring IGNORE / AVOID ───────────────────────────────────────────────────
# `IGNORE` is not a conclusion, it is a refusal to state one. Every no-action
# outcome must name which of these applies, so it can be checked and can expire.
NO_ACTION_REASONS = (
    "NO_VALID_ENTRY",
    "LOW_INFORMATION",
    "OUTSIDE_MANDATE",
    "POOR_LONG_TERM_THESIS",
    "TACTICALLY_EXTENDED",
    "EVENT_BLOCKED",
    "ILLIQUID",
    "NO_SUITABLE_INSTRUMENT",
    "DATA_STALE",
    "PORTFOLIO_CONFLICT",
)

# Words that may no longer stand alone as a verdict anywhere in the system.
RETIRED_LABELS = ("IGNORE", "AVOID")

# Phrases that are advice-shaped but mechanically empty. A recommendation
# containing one of these without a constructed blueprint is rejected by
# assert_no_vague_language() — this is the loophole-closer for the trade
# construction contract.
VAGUE_PHRASES = (
    "consider calls", "consider puts", "consider shorting", "consider going long",
    "consider a spread", "use a spread", "buy on weakness", "wait for breakout",
    "wait for a better entry", "hedge the position", "sell premium",
    "consider options", "look at calls", "look at puts",
)

# Fields no model may author. Provenance-checked, not merely documented.
DETERMINISTIC_FIELDS = frozenset({
    "price_used", "current_price", "price_drift_pct",
    "strike", "bid", "ask", "midpoint", "proposed_limit", "delta", "iv",
    "open_interest", "volume", "spread_pct", "contracts", "debit", "credit",
    "maximum_loss", "maximum_profit", "breakeven", "cash_required",
    "risk_per_share", "reward_to_risk", "width", "return_on_risk_pct",
    "effective_acquisition_price", "annualized_yield_pct", "occ_symbol",
    "earnings_inside_contract", "held_shares", "uncommitted_shares",
})


class DecisionPacketError(ValueError):
    """A packet that must not be displayed or acted on."""


@dataclass
class Dimension:
    """One horizon's independent view. Confidence is per-dimension on purpose:
    high confidence in a thesis and low confidence in timing is the NORMAL
    state for a volatile growth name, and one number cannot carry both."""
    direction: str = "UNRESOLVED"
    timing: str = "NO_VALID_SETUP"
    confidence: float = 0.0
    thesis: str = ""
    trigger: str = ""
    invalidation: str = ""

    def validate(self, horizon: str) -> list[str]:
        errs = []
        if self.direction not in DIRECTIONS:
            errs.append(f"{horizon}.direction {self.direction!r} not a valid direction")
        if self.timing not in TIMING_STATES:
            errs.append(f"{horizon}.timing {self.timing!r} not a valid timing state")
        if not 0.0 <= float(self.confidence) <= 1.0:
            errs.append(f"{horizon}.confidence {self.confidence} outside 0..1")
        # A directional call with no invalidation is unfalsifiable — it can never
        # be proven wrong, so it can never be learned from.
        if self.direction not in ("NEUTRAL", "UNRESOLVED") and not self.invalidation:
            errs.append(f"{horizon}: directional view requires an invalidation condition")
        # Likewise a conditional entry with no trigger is not a plan.
        if self.timing.startswith("WAIT_FOR") and not self.trigger:
            errs.append(f"{horizon}: {self.timing} requires a concrete trigger")
        return errs


def compose_headline(packet: dict) -> str:
    """The compact card line. Composed FROM the dimensions — never a substitute
    for them, and never one word."""
    lt = ((packet.get("horizons") or {}).get("long_term") or {})
    tac = ((packet.get("horizons") or {}).get("tactical") or {})
    ev = (packet.get("event_state") or {})
    dq = (packet.get("data_quality") or {})

    parts = []
    thesis = str(lt.get("thesis_state") or lt.get("direction") or "UNRESOLVED")
    parts.append(thesis.replace("_", " ").title() + " long term")
    parts.append(str(tac.get("timing") or "NO VALID SETUP").replace("_", " ").lower())

    if str(ev.get("impact") or "").upper() in ("CAUTION", "BLOCKED"):
        earn = (ev.get("earnings") or {}).get("date")
        parts.append(f"earnings {earn}" if earn else "event risk")

    if str(dq.get("state") or "").upper() in NON_ACTIONABLE_DATA:
        parts.append(str(dq.get("state")).lower() + " data")

    return " · ".join(parts)


def assert_no_vague_language(text: str, has_blueprint: bool) -> None:
    """Advice-shaped text with no mechanics is the failure mode this whole
    programme exists to prevent. 'Consider a call spread' is not a
    recommendation; it is the appearance of one."""
    low = str(text or "").lower()
    for phrase in VAGUE_PHRASES:
        if phrase in low and not has_blueprint:
            raise DecisionPacketError(
                f"vague strategy language {phrase!r} with no constructed blueprint — "
                "state the trigger, entry, stop, payoff and exact contract, or say "
                "why no trade can be constructed"
            )


def assert_not_retired(label: str) -> None:
    """IGNORE and AVOID are no longer conclusions."""
    up = str(label or "").strip().upper()
    if up in RETIRED_LABELS:
        raise DecisionPacketError(
            f"{up} is retired as a standalone verdict. Use a NO_ACTION_REASONS code "
            f"and state the horizon, the activity being avoided, and what would "
            f"change the decision. One of: {', '.join(NO_ACTION_REASONS)}"
        )


def validate(packet: dict, *, provenance: dict | None = None) -> list[str]:
    """Return a list of problems. Empty list means the packet may be displayed.

    `provenance` maps field name -> "deterministic" | "model". When supplied,
    any DETERMINISTIC_FIELDS marked "model" is an error: a model that invents a
    strike or a max-loss produces a number that looks calculated and is not.
    """
    errs: list[str] = []

    if not str(packet.get("symbol") or "").strip():
        errs.append("symbol is required")
    if not packet.get("evaluated_at"):
        errs.append("evaluated_at is required — an undated decision cannot go stale")

    horizons = packet.get("horizons") or {}
    for h in HORIZONS:
        if h not in horizons:
            errs.append(f"missing horizon {h!r} ({HORIZON_WINDOWS[h]}) — all three are required")
            continue
        d = horizons[h] or {}
        if h == "long_term":
            ts = d.get("thesis_state")
            if ts not in THESIS_STATES:
                errs.append(f"long_term.thesis_state {ts!r} not a valid thesis state")
        dim = Dimension(
            direction=d.get("direction", "UNRESOLVED"),
            timing=d.get("timing", "NO_VALID_SETUP"),
            confidence=d.get("confidence", 0.0) or 0.0,
            thesis=d.get("thesis", "") or "",
            trigger=d.get("trigger", "") or "",
            invalidation=d.get("invalidation", "") or "",
        )
        # long_term expresses conviction, not a session-level setup, so timing is
        # exempt there; the other two horizons must state one.
        errs.extend(e for e in dim.validate(h)
                    if not (h == "long_term" and ".timing" in e))

    ev = packet.get("event_state") or {}
    if str(ev.get("impact") or "UNKNOWN").upper() not in EVENT_STATES:
        errs.append(f"event_state.impact {ev.get('impact')!r} invalid")

    dq = packet.get("data_quality") or {}
    dq_state = str(dq.get("state") or "INSUFFICIENT").upper()
    if dq_state not in DATA_STATES:
        errs.append(f"data_quality.state {dq.get('state')!r} invalid")

    # The BETA defect in one rule: a stale packet may not present an actionable
    # preferred action as though it were current.
    pref = packet.get("preferred_action") or {}
    if dq_state in NON_ACTIONABLE_DATA and pref.get("structure") not in (None, "", "NO_TRADE"):
        if not pref.get("prior_thesis_label"):
            errs.append(
                f"data_quality={dq_state} but preferred_action={pref.get('structure')!r} "
                f"is presented as current — a non-revalidated packet must carry "
                f"prior_thesis_label={PRIOR_THESIS_LABEL!r}"
            )

    for key in ("bullish_structures", "bearish_structures", "held_position_actions"):
        for s in (packet.get(key) or []):
            name, state = s.get("structure"), s.get("state")
            if name not in ALL_STRUCTURES:
                errs.append(f"{key}: unknown structure {name!r}")
            if state not in STRUCTURE_STATES:
                errs.append(f"{key}: {name} has invalid state {state!r}")
            # A rejection with no reason is indistinguishable from an oversight.
            if state == "REJECTED" and not (s.get("rejection_reasons") or []):
                errs.append(f"{key}: {name} REJECTED without rejection_reasons")
            if state == "CONDITIONAL" and not (s.get("activation_trigger") or {}):
                errs.append(f"{key}: {name} CONDITIONAL without activation_trigger")
            if name in RESEARCH_ONLY and state == "ELIGIBLE":
                errs.append(f"{key}: {name} is research-only and may not be ELIGIBLE")

    # no_trade must always be a reachable answer. A system that cannot say
    # "nothing here" will always find something.
    if "no_trade_is_valid" not in packet:
        errs.append("no_trade_is_valid must be stated explicitly")

    if provenance:
        for fname, owner in provenance.items():
            if fname in DETERMINISTIC_FIELDS and str(owner).lower() == "model":
                errs.append(
                    f"field {fname!r} is deterministic-only but provenance says 'model' — "
                    "a model may interpret evidence, never author a quote or payoff number"
                )

    return errs


def is_actionable(packet: dict) -> tuple[bool, str]:
    """(actionable, reason). Actionability is a property of the packet, not a
    judgement about the company — a great company with stale data is not
    actionable, and that is not a criticism of the company."""
    dq = str(((packet.get("data_quality") or {}).get("state")) or "INSUFFICIENT").upper()
    if dq in NON_ACTIONABLE_DATA:
        return False, f"DATA_STALE: packet data_quality={dq}"
    ev = str(((packet.get("event_state") or {}).get("impact")) or "UNKNOWN").upper()
    if ev == "BLOCKED":
        return False, "EVENT_BLOCKED: a material event blocks action"
    if ev == "UNKNOWN":
        return False, "EVENT_BLOCKED: event state could not be established (fails closed)"
    pref = (packet.get("preferred_action") or {}).get("structure")
    if not pref or pref == "NO_TRADE":
        return False, "NO_VALID_ENTRY: no structure preferred"
    return True, ""
