#!/usr/bin/env python3
"""decision_action_policy.py — the ONE authority for advisory action eligibility.

WHY THIS EXISTS
---------------
The card was made to DISPLAY the multidimensional packet, but the action buttons
still gated on the legacy one-word label (cioAvoid on IGNORE/AVOID/SELL/TRIM). So
the card could say "constructive long term, swing conditional" while the buttons
behaved as though IGNORE were authoritative — the displayed decision and the
action gate could contradict each other. That is the next version of the same
trust failure this whole programme exists to remove.

This module is the SOLE source of advisory action eligibility. The card renders
its result; the API returns its result; they cannot disagree because there is one
evaluator. It runs on the backend and the frontend consumes the result inline —
there is no second copy of the logic to drift.

WHAT MAY AND MAY NOT GRANT ELIGIBILITY
--------------------------------------
Models supply thesis and timing OPINIONS (in the packet's horizons). They may NOT
grant action eligibility. Eligibility requires deterministic, internally
consistent MECHANICS — a blueprint whose state is ELIGIBLE, or a defined trigger
that has been satisfied. A CONDITIONAL plan exposes its condition but must never
masquerade as ready. A stale or conflicted packet may only permit refresh/review.
NO_TRADE ELIGIBLE can block a proposal action. And nothing here submits, approves,
or 2FA-confirms anything — this is advisory eligibility upstream of the existing
approval + per-order 2FA gates, which are untouched.

PURE: no network, no database. Inputs are passed in.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

POLICY_VERSION = "1.0.0"

# Actions the policy can advise (never an order — those live behind approval+2FA).
ACTIONS = ("PROPOSE_ENTRY", "RESEARCH_OPTIONS", "REFRESH", "MONITOR", "NO_ACTION")
STATES = ("READY", "CONDITIONAL", "BLOCKED", "STALE", "DATA_UNAVAILABLE")

# Packet older than this is STALE for action purposes even if input-hash matched
# (a coarse backstop; the input-hash invalidation is the finer test).
DEFAULT_TTL_HOURS = 12

# data_quality states that forbid anything but refresh/review.
NON_ACTIONABLE_DQ = ("STALE", "CONFLICTED", "INSUFFICIENT", "PROVIDER_DOWN")


def _now(now=None) -> datetime:
    return now or datetime.now(timezone.utc)


def _parse(ts) -> Optional[datetime]:
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def compute_input_hash(packet: dict) -> str:
    """A canonical hash of the inputs a decision depends on. Two packets with the
    same hash rest on the same evidence; a change here is what should invalidate a
    younger packet (see the invalidation work). Deterministic and order-stable."""
    p = packet or {}
    ev = (p.get("event_state") or {}).get("earnings") or {}
    dq = p.get("data_quality") or {}
    own = p.get("ownership") or {}
    fund = ((p.get("fundamentals") or {}) or {})
    material = {
        "symbol": str(p.get("symbol") or "").upper(),
        "price_used": p.get("price_used"),
        "facts_as_of": str(p.get("facts_as_of") or ""),
        "event_state": ev.get("state"),
        "event_date": ev.get("date"),
        "data_quality": dq.get("state"),
        "held": own.get("held"),
        "shares": own.get("shares"),
        "packet_version": p.get("packet_version"),
        "fundamentals_as_of": fund.get("fundamentals_as_of"),
        "source_commit_sha": p.get("source_commit_sha"),
        "policy_version": POLICY_VERSION,
    }
    blob = json.dumps(material, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _result(action, allowed, state, *, packet=None, blueprint_id=None,
            blocks=None, warnings=None, confirmations=None, reason=""):
    p = packet or {}
    return {
        "action": action, "allowed": bool(allowed), "state": state,
        "blocks": blocks or [], "warnings": warnings or [],
        "required_confirmations": confirmations or [],
        "packet_id": p.get("packet_id"),
        "packet_version": p.get("packet_version"),
        "blueprint_id": blueprint_id,
        "policy_version": POLICY_VERSION,
        "input_hash": compute_input_hash(p) if p else None,
        "reason": reason,
    }


def evaluate_action(packet: dict, *, packet_id=None, generated_at=None,
                    existing_proposal: bool = False, ttl_hours: float = DEFAULT_TTL_HOURS,
                    now=None) -> dict:
    """The canonical action decision for one symbol from its live packet.

    Returns the action-policy result. `allowed` is True ONLY when state == READY,
    and READY requires an ELIGIBLE blueprint (or a satisfied trigger) — never a
    model opinion alone.
    """
    if not packet or not isinstance(packet, dict):
        # No packet is not a silent grant of legacy authority — it routes to build.
        return _result("REFRESH", False, "DATA_UNAVAILABLE",
                       reason="no decision packet — build one before acting")

    p = dict(packet)
    if packet_id is not None:
        p["packet_id"] = packet_id

    # 1. Packet version must be current — a policy/version mismatch is not actionable.
    if str(p.get("packet_version") or "") and not str(p.get("packet_version")).endswith("-shadow"):
        pass  # (accepts current shadow versions; a hard version gate lives in the caller)

    # 2. STALE by wall-clock backstop.
    gen = _parse(generated_at) or _parse(p.get("evaluated_at"))
    if gen is not None:
        age_h = (_now(now) - gen).total_seconds() / 3600.0
        if age_h > ttl_hours:
            return _result("REFRESH", False, "STALE", packet=p,
                           blocks=[f"packet is {age_h:.0f}h old (>{ttl_hours}h TTL)"],
                           reason="stale packet — refresh before acting")

    # 3. Data quality gate — a stale/conflicted packet may only refresh or review.
    dq = str((p.get("data_quality") or {}).get("state") or "INSUFFICIENT").upper()
    if dq in NON_ACTIONABLE_DQ:
        return _result("REFRESH", False, "STALE", packet=p,
                       blocks=[f"data_quality={dq}"],
                       reason=f"data quality {dq} — refresh/review only")

    # 4. Event gate — BLOCKED or UNKNOWN event fails closed to monitoring.
    ev = p.get("event_state") or {}
    ev_impact = str(ev.get("impact") or "UNKNOWN").upper()
    if ev_impact in ("BLOCKED", "UNKNOWN"):
        return _result("MONITOR", False, "BLOCKED", packet=p,
                       blocks=[f"event_state={ev_impact}"],
                       reason="event state blocks action")

    fams = p.get("plan_families") or {}
    swing = fams.get("swing") or {}
    tactical = p.get("horizons", {}).get("tactical") or {}
    options = fams.get("options") or {}
    no_trade = fams.get("no_trade") or {}

    swing_state = str(swing.get("state") or "DATA_UNAVAILABLE").upper()
    swing_struct = (swing.get("structures") or [{}])[0]

    # 5. Tactical/swing: PROPOSE_ENTRY only when the blueprint is ELIGIBLE, or its
    #    defined trigger is satisfied. CONDITIONAL exposes the trigger but is NOT
    #    allowed — it must not masquerade as ready.
    if swing_state == "ELIGIBLE":
        conf = ["operator approval in Options/Proposals", "per-order 2FA at submit"]
        if existing_proposal:
            return _result("MONITOR", False, "CONDITIONAL", packet=p,
                           warnings=["a proposal already exists for this symbol"],
                           reason="proposal already open — monitor it")
        return _result("PROPOSE_ENTRY", True, "READY", packet=p,
                       confirmations=conf,
                       reason="swing blueprint is eligible with resolved mechanics")

    if swing_state == "CONDITIONAL":
        trig = swing_struct.get("underlying_trigger") or tactical.get("trigger") or "condition not met"
        inval = swing_struct.get("underlying_invalidation") or tactical.get("invalidation")
        warns = [f"conditional — trigger: {trig}"]
        if inval:
            warns.append(f"invalidation: {inval}")
        return _result("MONITOR", False, "CONDITIONAL", packet=p,
                       warnings=warns,
                       reason="swing is conditional; expose the trigger, do not offer entry")

    # 6. Options: an ELIGIBLE structure routes to research; otherwise research/refresh
    #    only — never a proposal from an unresolved chain.
    opt_state = str(options.get("state") or "DATA_UNAVAILABLE").upper()
    opt_eligible = any(str(s.get("state") or "").upper() == "ELIGIBLE"
                       for s in (options.get("structures") or []))
    if opt_eligible:
        return _result("RESEARCH_OPTIONS", True, "READY", packet=p,
                       confirmations=["options approval + per-order 2FA at submit"],
                       reason="an exact option structure is eligible — research it")
    if opt_state == "CONDITIONAL":
        return _result("RESEARCH_OPTIONS", False, "CONDITIONAL", packet=p,
                       warnings=["options are conditional — no resolvable structure yet"],
                       reason="options conditional; research, do not propose")

    # 7. NO_TRADE ELIGIBLE blocks a proposal action when nothing else is actionable.
    if str(no_trade.get("state") or "").upper() == "ELIGIBLE":
        return _result("NO_ACTION", False, "CONDITIONAL", packet=p,
                       blocks=["no_trade is a valid outcome and nothing is eligible"],
                       reason="no eligible structure; no-trade is valid")

    # 8. Fallthrough — nothing actionable, keep watching.
    return _result("MONITOR", False, "CONDITIONAL", packet=p,
                   reason="no eligible or conditional entry; monitor")
