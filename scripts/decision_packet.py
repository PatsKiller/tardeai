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


def rollup_family_state(structures: list) -> str:
    """The family state implied by its child structures — the STRICT invariant.

    A family cannot be CONDITIONAL merely because some structures are REJECTED
    (the BETA options bug: OPTIONS showed CONDITIONAL while every structure was
    REJECTED/NOT_APPLICABLE). CONDITIONAL requires at least one CONDITIONAL child
    — which includes an explicit wait/re-evaluation blueprint such as
    POST_EARNINGS_REEVALUATION.

        ELIGIBLE         >= 1 ELIGIBLE child
        CONDITIONAL      no ELIGIBLE, but >= 1 CONDITIONAL child
        REJECTED         >= 1 applicable child, all REJECTED (or REJECTED+N/A)
        NOT_APPLICABLE   every child structurally inapplicable
        DATA_UNAVAILABLE no children, or evaluation could not complete
    """
    states = [str(s.get("state") or "").upper() for s in (structures or [])]
    if not states:
        return "DATA_UNAVAILABLE"
    if "ELIGIBLE" in states:
        return "ELIGIBLE"
    if "CONDITIONAL" in states:
        return "CONDITIONAL"
    applicable = [s for s in states if s != "NOT_APPLICABLE"]
    if not applicable:
        return "NOT_APPLICABLE"
    if all(s in ("REJECTED", "NOT_APPLICABLE") for s in states):
        return "REJECTED"
    return "DATA_UNAVAILABLE"


# ── Three-axis family state (constructibility ≠ decision ≠ action) ────────────
# A mechanically constructible ladder is not an eligible ownership recommendation,
# and an eligible decision under EVENT_BLOCKED is never READY. Overloading one
# `state` word produced MRLN "EVENT BLOCKED / Swing ELIGIBLE · READY".

CONSTRUCTIBILITY_STATES = ("CONSTRUCTIBLE", "UNCONSTRUCTIBLE", "DATA_UNAVAILABLE")
ACTION_STATES = ("READY", "CONDITIONAL", "BLOCKED", "STALE", "DATA_UNAVAILABLE")

THESIS_REJECTS_LONG_TERM = frozenset({
    "FUNDAMENTALLY_UNATTRACTIVE", "DETERIORATING",
})
THESIS_DATA_UNAVAILABLE = frozenset({"INSUFFICIENT_EVIDENCE"})
THESIS_CONDITIONAL = frozenset({"NEUTRAL"})
THESIS_MAY_ELIGIBLE = frozenset({
    "STRONG_CONVICTION", "CONSTRUCTIVE", "SPECULATIVE_CONSTRUCTIVE",
})
# Timing states that block action even when mechanics exist.
EVENT_BLOCK_TIMINGS = frozenset({"EVENT_BLOCKED"})
# Timing states that make a constructible long-term ladder CONDITIONAL, not ELIGIBLE.
TIMING_SOFT_CONDITIONAL = frozenset({
    "EXTENDED", "WAIT_FOR_PULLBACK", "WAIT_FOR_BREAKOUT", "BREAKOUT_CONFIRMATION",
})


def thesis_to_long_term_decision(thesis_state: str) -> str:
    """Map long-term thesis → decision_state. Mechanics alone never grant ELIGIBLE."""
    t = str(thesis_state or "").upper()
    if t in THESIS_REJECTS_LONG_TERM:
        return "REJECTED"
    if t in THESIS_DATA_UNAVAILABLE:
        return "DATA_UNAVAILABLE"
    if t in THESIS_CONDITIONAL:
        return "CONDITIONAL"
    if t in THESIS_MAY_ELIGIBLE:
        return "ELIGIBLE"
    return "DATA_UNAVAILABLE"


def event_blocks_action(packet: dict) -> bool:
    """True when event policy or tactical timing forbids READY action."""
    tac = ((packet.get("horizons") or {}).get("tactical") or {})
    if str(tac.get("timing") or "").upper() in EVENT_BLOCK_TIMINGS:
        return True
    impact = str(((packet.get("event_state") or {}).get("impact") or "UNKNOWN")).upper()
    return impact in ("BLOCKED", "UNKNOWN")


def _ensure_conditional_trigger(structure: dict) -> None:
    """CONDITIONAL children must carry an activation_trigger object."""
    if str(structure.get("state") or "").upper() != "CONDITIONAL":
        return
    if structure.get("activation_trigger"):
        return
    structure["activation_trigger"] = {
        "trigger": (structure.get("condition") or structure.get("event")
                    or structure.get("underlying_trigger") or "re-evaluate"),
        "reason": structure.get("why_preferred") or structure.get("condition") or "",
        "required_data": structure.get("data_required"),
        "reevaluate_after": structure.get("reevaluate_after"),
        "action_state": "CONDITIONAL",
        "rejection_conditions": structure.get("rejection_reasons") or [],
    }


def _downgrade_eligible_structures(structures: list, *, to_state: str, reason: str) -> None:
    for s in structures or []:
        if str(s.get("state") or "").upper() == "ELIGIBLE":
            s["state"] = to_state
            s.setdefault("rejection_reasons", [])
            if reason not in (s.get("rejection_reasons") or []):
                s["rejection_reasons"] = list(s.get("rejection_reasons") or []) + [reason]


def materialize_packet(packet: dict) -> dict:
    """THE single egress gate for any live decision packet.

    Every API/UI path that surfaces a packet must run this. It is the root fix
    for cross-layer contradictions (thesis vs family, event vs READY, options
    roll-up, no-trade veto, three-axis states) — not a per-symbol patch list.
    Idempotent: safe to call on already-reconciled packets.
    """
    if not isinstance(packet, dict):
        return packet
    return reconcile_plan_families(dict(packet))


def reconcile_plan_families(packet: dict) -> dict:
    """Enforce three-axis family semantics on a packet (in place).

    Separates constructibility / decision / action, applies thesis and event
    gates, re-rolls options from children, and rewrites NO_TRADE as
    available/preferred/dominant rather than a blanket ELIGIBLE veto.
    """
    if not isinstance(packet, dict):
        return packet
    fams = dict(packet.get("plan_families") or {})
    thesis = str(((packet.get("horizons") or {}).get("long_term") or {}).get("thesis_state") or "").upper()
    timing = str(((packet.get("horizons") or {}).get("tactical") or {}).get("timing") or "").upper()
    dq = str(((packet.get("data_quality") or {}).get("state") or "INSUFFICIENT")).upper()
    blocked = event_blocks_action(packet)
    stale_dq = dq in NON_ACTIONABLE_DATA

    def _axes(family_key: str, fam: dict, *, constr: str, decision: str,
              action: str, blocks=None, conditions=None) -> dict:
        out = dict(fam or {})
        out["family"] = out.get("family") or family_key.upper()
        out["constructibility_state"] = constr
        out["decision_state"] = decision
        out["action_state"] = action
        # `state` remains the decision_state for DB columns / legacy consumers.
        out["state"] = decision
        out["blocks"] = list(blocks or out.get("blocks") or [])
        out["conditions"] = list(conditions or out.get("conditions") or [])
        for s in (out.get("structures") or []):
            _ensure_conditional_trigger(s)
        return out

    # ── LONG_TERM ────────────────────────────────────────────────────────────
    lt = dict(fams.get("long_term") or {"family": "LONG_TERM", "structures": []})
    lt_structs = list(lt.get("structures") or [])
    if not lt_structs:
        lt_constr = "DATA_UNAVAILABLE" if not lt.get("rejection_reasons") else "UNCONSTRUCTIBLE"
    elif any(str(s.get("state") or "").upper() in ("ELIGIBLE", "CONDITIONAL")
             or s.get("structure") for s in lt_structs):
        lt_constr = "CONSTRUCTIBLE"
    else:
        lt_constr = "UNCONSTRUCTIBLE"
    lt_decision = thesis_to_long_term_decision(thesis)
    if lt_decision == "ELIGIBLE" and timing in TIMING_SOFT_CONDITIONAL:
        lt_decision = "CONDITIONAL"
    if lt_constr == "DATA_UNAVAILABLE" and lt_decision == "ELIGIBLE":
        lt_decision = "DATA_UNAVAILABLE"
    if lt_decision in ("REJECTED", "DATA_UNAVAILABLE"):
        _downgrade_eligible_structures(
            lt_structs, to_state=lt_decision if lt_decision == "REJECTED" else "DATA_UNAVAILABLE",
            reason=f"long-term thesis {thesis or 'UNRESOLVED'} forbids ELIGIBLE ownership recommendation")
        lt["structures"] = lt_structs
        lt["rejection_reasons"] = list(lt.get("rejection_reasons") or []) + [
            f"thesis {thesis} → decision_state {lt_decision}"]
    if blocked:
        lt_action = "BLOCKED"
    elif stale_dq:
        lt_action = "STALE"
    elif lt_decision == "ELIGIBLE" and lt_constr == "CONSTRUCTIBLE":
        lt_action = "READY"
    elif lt_decision == "CONDITIONAL":
        lt_action = "CONDITIONAL"
    elif lt_decision == "REJECTED":
        lt_action = "BLOCKED"
    else:
        lt_action = "DATA_UNAVAILABLE"
    fams["long_term"] = _axes("LONG_TERM", lt, constr=lt_constr, decision=lt_decision,
                              action=lt_action,
                              blocks=(["EVENT_BLOCKED"] if blocked else []) + list(lt.get("rejection_reasons") or []))

    # ── SWING ────────────────────────────────────────────────────────────────
    sw = dict(fams.get("swing") or {"family": "SWING", "structures": []})
    sw_structs = list(sw.get("structures") or [])
    raw_sw = str(sw.get("state") or "").upper()
    # A child in ELIGIBLE/CONDITIONAL state implies mechanics were constructible
    # (even if the structure dict is sparse in tests / partial persistence).
    if not sw_structs:
        sw_constr = "DATA_UNAVAILABLE"
    elif any(str(s.get("state") or "").upper() in ("ELIGIBLE", "CONDITIONAL")
             or s.get("entry_zone") or s.get("limit_price") or s.get("structure")
             for s in sw_structs):
        sw_constr = "CONSTRUCTIBLE"
    else:
        sw_constr = "UNCONSTRUCTIBLE"
    sw_decision = raw_sw if raw_sw in STRUCTURE_STATES else "DATA_UNAVAILABLE"
    # Timing NO_VALID_SETUP cannot leave decision as ELIGIBLE.
    if timing in ("NO_VALID_SETUP",) and sw_decision == "ELIGIBLE":
        sw_decision = "CONDITIONAL"
        _downgrade_eligible_structures(
            sw_structs, to_state="CONDITIONAL",
            reason=f"tactical timing {timing} — setup defined but not an active entry")
        sw["structures"] = sw_structs
    sw_blocks = list(sw.get("rejection_reasons") or [])
    if blocked:
        if sw_decision == "ELIGIBLE":
            sw_decision = "CONDITIONAL"
            _downgrade_eligible_structures(
                sw_structs, to_state="CONDITIONAL",
                reason="EVENT_BLOCKED — mechanics remain constructible but action is blocked")
            sw["structures"] = sw_structs
        sw_action = "BLOCKED"
        sw_blocks = ["EVENT_BLOCKED"] + sw_blocks
    elif stale_dq:
        sw_action = "STALE"
    elif sw_decision == "ELIGIBLE" and sw_constr == "CONSTRUCTIBLE":
        sw_action = "READY"
    elif sw_decision == "CONDITIONAL":
        sw_action = "CONDITIONAL"
    elif sw_decision in ("REJECTED", "NOT_APPLICABLE"):
        sw_action = "BLOCKED" if sw_decision == "REJECTED" else "DATA_UNAVAILABLE"
    else:
        sw_action = "DATA_UNAVAILABLE"
    # Absolute invariant: EVENT_BLOCKED never yields READY.
    if blocked and sw_action == "READY":
        sw_action = "BLOCKED"
    fams["swing"] = _axes("SWING", sw, constr=sw_constr, decision=sw_decision,
                          action=sw_action, blocks=sw_blocks)

    # ── BEARISH ──────────────────────────────────────────────────────────────
    be = dict(fams.get("bearish") or {"family": "BEARISH", "structures": []})
    be_structs = list(be.get("structures") or [])
    # Re-rollup from children when present.
    be_decision = (rollup_family_state(be_structs) if be_structs
                   else str(be.get("state") or "DATA_UNAVAILABLE").upper())
    if be_structs and be_decision != "DATA_UNAVAILABLE":
        be_constr = "CONSTRUCTIBLE" if be_decision in ("ELIGIBLE", "CONDITIONAL", "REJECTED") else "UNCONSTRUCTIBLE"
    else:
        be_constr = "DATA_UNAVAILABLE"
    # Held-long conflict must dominate borrow UNKNOWN when ownership.held.
    own = packet.get("ownership") or {}
    if own.get("held"):
        for s in be_structs:
            reasons = list(s.get("rejection_reasons") or [])
            if not any("held long" in str(r).lower() for r in reasons):
                reasons = ["symbol is currently held long — shorting it would offset the position"] + reasons
                s["rejection_reasons"] = reasons
                if str(s.get("state") or "").upper() == "ELIGIBLE":
                    s["state"] = "REJECTED"
        if be_structs:
            be_decision = rollup_family_state(be_structs)
            be["structures"] = be_structs
    if blocked:
        be_action = "BLOCKED"
        if be_decision == "ELIGIBLE":
            be_decision = "CONDITIONAL"
    elif stale_dq:
        be_action = "STALE"
    elif be_decision == "ELIGIBLE":
        be_action = "READY"
    elif be_decision == "CONDITIONAL":
        be_action = "CONDITIONAL"
    elif be_decision == "REJECTED":
        be_action = "BLOCKED"
    else:
        be_action = "DATA_UNAVAILABLE"
    fams["bearish"] = _axes("BEARISH", be, constr=be_constr, decision=be_decision,
                            action=be_action,
                            blocks=list(be.get("rejection_reasons") or []))

    # ── OPTIONS (strict child roll-up) ───────────────────────────────────────
    op = dict(fams.get("options") or {"family": "OPTIONS", "structures": []})
    op_structs = list(op.get("structures") or [])
    for s in op_structs:
        _ensure_conditional_trigger(s)
    # Covered-call / collar applicability must use ownership.uncommitted_shares when set.
    uncommitted = own.get("uncommitted_shares")
    shares = float(own.get("shares") or 0)
    held = bool(own.get("held"))
    avail = uncommitted if uncommitted is not None else (shares if held else 0.0)
    for s in op_structs:
        name = str(s.get("structure") or "").upper()
        if name in ("COVERED_CALL", "COLLAR", "BUY_WRITE"):
            if avail < 100:
                s["state"] = "NOT_APPLICABLE"
                s["rejection_reasons"] = [
                    f"{name} requires ≥100 uncommitted shares; available={avail:g}, "
                    f"held={shares:g}, packet.ownership.held={held}"
                ]
    op_decision = rollup_family_state(op_structs) if op_structs else str(
        op.get("state") or "DATA_UNAVAILABLE").upper()
    if not op_structs:
        op_constr = "DATA_UNAVAILABLE"
    elif any(str(s.get("state") or "").upper() in ("ELIGIBLE", "CONDITIONAL") for s in op_structs):
        op_constr = "CONSTRUCTIBLE"
    elif any(str(s.get("state") or "").upper() == "REJECTED" for s in op_structs):
        op_constr = "UNCONSTRUCTIBLE"  # evaluated, refused
    else:
        op_constr = "DATA_UNAVAILABLE"
    op["structures"] = op_structs
    if blocked:
        op_action = "BLOCKED"
        if op_decision == "ELIGIBLE":
            op_decision = "CONDITIONAL"
            _downgrade_eligible_structures(
                op_structs, to_state="CONDITIONAL",
                reason="EVENT_BLOCKED — option mechanics suppressed for action")
            op["structures"] = op_structs
            op_decision = rollup_family_state(op_structs)
    elif stale_dq:
        op_action = "STALE"
    elif op_decision == "ELIGIBLE":
        op_action = "READY"
    elif op_decision == "CONDITIONAL":
        op_action = "CONDITIONAL"
    elif op_decision == "REJECTED":
        op_action = "BLOCKED"
    else:
        op_action = "DATA_UNAVAILABLE"
    fams["options"] = _axes("OPTIONS", op, constr=op_constr, decision=op_decision,
                            action=op_action,
                            blocks=list(op.get("rejection_reasons") or []))

    # ── NO_TRADE (available ≠ preferred ≠ dominant) ──────────────────────────
    any_ready = any(str((fams.get(k) or {}).get("action_state") or "").upper() == "READY"
                    for k in ("long_term", "swing", "bearish", "options"))
    any_eligible = any(str((fams.get(k) or {}).get("decision_state") or "").upper() == "ELIGIBLE"
                       for k in ("long_term", "swing", "bearish", "options"))
    preferred = (not any_ready and not any_eligible) or stale_dq
    dominant = False  # model text alone never makes no-trade dominant
    reason = ("data quality forbids other actions" if stale_dq and preferred
              else "no eligible constructible plan family" if preferred
              else "no-trade remains a valid alternative; does not veto other plans")
    fams["no_trade"] = {
        "family": "NO_TRADE",
        "available": True,
        "preferred": preferred,
        "dominant": dominant,
        "reason": reason,
        # decision_state: NOT_APPLICABLE when merely available; ELIGIBLE when preferred.
        "constructibility_state": "CONSTRUCTIBLE",
        "decision_state": "ELIGIBLE" if preferred else "NOT_APPLICABLE",
        "action_state": "READY" if preferred else "CONDITIONAL",
        "state": "ELIGIBLE" if preferred else "NOT_APPLICABLE",
        "blocks": [],
        "conditions": [],
        "structures": [],
        "rationale": reason,
    }

    packet["plan_families"] = fams
    packet["no_trade_is_valid"] = True
    return packet


def assert_family_invariants(packet: dict) -> list[str]:
    """Return invariant violations across thesis/event/options/no-trade axes."""
    errs: list[str] = []
    if not isinstance(packet, dict):
        return ["packet is not a dict"]
    fams = packet.get("plan_families") or {}
    thesis = str(((packet.get("horizons") or {}).get("long_term") or {}).get("thesis_state") or "").upper()
    lt = fams.get("long_term") or {}
    sw = fams.get("swing") or {}
    op = fams.get("options") or {}
    nt = fams.get("no_trade") or {}

    lt_dec = str(lt.get("decision_state") or lt.get("state") or "").upper()
    if thesis in THESIS_REJECTS_LONG_TERM and lt_dec == "ELIGIBLE":
        errs.append(f"thesis {thesis} cannot coexist with long-term ELIGIBLE")
    if thesis in THESIS_DATA_UNAVAILABLE and lt_dec == "ELIGIBLE":
        errs.append(f"thesis {thesis} cannot coexist with long-term ELIGIBLE")

    if event_blocks_action(packet):
        for key, fam in (("swing", sw), ("long_term", lt), ("options", op)):
            act = str(fam.get("action_state") or "").upper()
            if act == "READY":
                errs.append(f"EVENT_BLOCKED cannot coexist with {key} READY")
            if str(fam.get("decision_state") or fam.get("state") or "").upper() == "ELIGIBLE" and act == "READY":
                errs.append(f"EVENT_BLOCKED family {key} must not render ELIGIBLE·READY")

    kids = op.get("structures") or []
    op_dec = str(op.get("decision_state") or op.get("state") or "").upper()
    if op_dec == "CONDITIONAL":
        if not any(str(s.get("state") or "").upper() == "CONDITIONAL" for s in kids):
            errs.append("options CONDITIONAL requires at least one CONDITIONAL child")
        for s in kids:
            if str(s.get("state") or "").upper() == "CONDITIONAL" and not (
                    s.get("activation_trigger") or s.get("condition") or s.get("reevaluate_after")):
                errs.append(f"options child {s.get('structure')} CONDITIONAL lacks trigger/reason")

    if kids and op_dec != rollup_family_state(kids):
        errs.append(f"options decision_state {op_dec} != rollup {rollup_family_state(kids)}")

    # No-trade available alone must not look like a veto (ELIGIBLE) when other families are ready.
    if nt.get("available") and not nt.get("preferred") and not nt.get("dominant"):
        if str(nt.get("decision_state") or nt.get("state") or "").upper() == "ELIGIBLE":
            # After reconcile, non-preferred no-trade is NOT_APPLICABLE; flag legacy shape.
            errs.append("no-trade available-but-not-preferred must not be decision ELIGIBLE")

    for key in ("long_term", "swing", "bearish", "options"):
        fam = fams.get(key) or {}
        if fam and not fam.get("constructibility_state"):
            errs.append(f"{key} missing constructibility_state")
        if fam and not fam.get("action_state"):
            errs.append(f"{key} missing action_state")

    return errs


def is_actionable(packet: dict) -> tuple[bool, str]:
    """(actionable, reason). Actionability is a property of the packet, not a
    judgement about the company — a great company with stale data is not
    actionable, and that is not a criticism of the company."""
    dq = str(((packet.get("data_quality") or {}).get("state")) or "INSUFFICIENT").upper()
    if dq in NON_ACTIONABLE_DATA:
        return False, f"DATA_STALE: packet data_quality={dq}"
    if event_blocks_action(packet):
        return False, "EVENT_BLOCKED: a material event or tactical timing blocks action"
    pref = (packet.get("preferred_action") or {}).get("structure")
    nt = (packet.get("plan_families") or {}).get("no_trade") or {}
    if nt.get("preferred") or nt.get("dominant"):
        return False, "NO_TRADE preferred/dominant"
    if not pref or pref == "NO_TRADE":
        return False, "NO_VALID_ENTRY: no structure preferred"
    return True, ""
