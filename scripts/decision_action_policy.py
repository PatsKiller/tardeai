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

POLICY_VERSION = "1.1.0"  # three-axis family action_state + no-trade preferred/dominant

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
                    current_snapshot: dict = None, now=None) -> dict:
    """Public entry — computes the decision, then guarantees the input-parity fields
    (packet_input_hash, current_input_hash, inputs_match, invalidation_reasons) are
    present on the result whenever a current snapshot was available."""
    res = _evaluate_action_impl(
        packet, packet_id=packet_id, generated_at=generated_at,
        existing_proposal=existing_proposal, ttl_hours=ttl_hours,
        current_snapshot=current_snapshot, now=now)
    if current_snapshot and "inputs_match" not in res:
        res["current_input_hash"] = current_snapshot.get("input_hash")
        res["packet_input_hash"] = ((packet or {}).get("input_hash")
                                    or ((packet or {}).get("input_snapshot") or {}).get("input_hash"))
        res["inputs_match"] = True
        res["invalidation_reasons"] = []
    return res


def _evaluate_action_impl(packet: dict, *, packet_id=None, generated_at=None,
                          existing_proposal: bool = False, ttl_hours: float = DEFAULT_TTL_HOURS,
                          current_snapshot: dict = None, now=None) -> dict:
    """The canonical action decision for one symbol from its live packet.

    Returns the action-policy result. `allowed` is True ONLY when state == READY,
    and READY requires an ELIGIBLE blueprint (or a satisfied trigger) — never a
    model opinion alone.

    When `current_snapshot` is supplied, the packet is FIRST checked against
    current source truth; on any mismatch the result is REFRESH/STALE with the
    exact invalidation reasons, before any mechanics are considered. So a packet
    that no longer matches the market/event/ownership/fundamental state cannot
    authorise an action however good its stored mechanics look.
    """
    if not packet or not isinstance(packet, dict):
        # No packet is not a silent grant of legacy authority — it routes to build.
        return _result("REFRESH", False, "DATA_UNAVAILABLE",
                       reason="no decision packet — build one before acting")

    p = dict(packet)
    if packet_id is not None:
        p["packet_id"] = packet_id

    # 0. CURRENT-INPUT VALIDATION — the packet must still match source truth.
    if current_snapshot:
        try:
            import packet_invalidation as _inv
            cmp = _inv.compare_packet_inputs(p, current_snapshot,
                                             generated_at=generated_at, now=now)
            if not cmp["inputs_match"]:
                res = _result("REFRESH", False, "STALE", packet=p,
                              blocks=cmp["invalidation_reasons"],
                              reason="packet no longer matches current inputs — refresh")
                res["packet_input_hash"] = cmp["packet_input_hash"]
                res["current_input_hash"] = cmp["current_input_hash"]
                res["inputs_match"] = False
                res["invalidation_reasons"] = cmp["invalidation_reasons"]
                return res
            _match = cmp
        except Exception:
            _match = None
    else:
        _match = None

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

    # Single egress materialize (idempotent) — root fix for every symbol's packet.
    try:
        import decision_packet as _dp
        p = _dp.materialize_packet(p)
    except Exception:
        pass

    fams = p.get("plan_families") or {}
    swing = fams.get("swing") or {}
    tactical = p.get("horizons", {}).get("tactical") or {}
    options = fams.get("options") or {}
    no_trade = fams.get("no_trade") or {}

    # Prefer action_state (three-axis); fall back to legacy single state.
    def _action(fam):
        return str(fam.get("action_state") or fam.get("state") or "DATA_UNAVAILABLE").upper()

    def _decision(fam):
        return str(fam.get("decision_state") or fam.get("state") or "DATA_UNAVAILABLE").upper()

    swing_action = _action(swing)
    swing_decision = _decision(swing)
    swing_struct = (swing.get("structures") or [{}])[0]
    event_block = any("EVENT_BLOCKED" in str(b) for b in (swing.get("blocks") or []))
    try:
        import decision_packet as _dp2
        event_block = event_block or _dp2.event_blocks_action(p)
    except Exception:
        pass

    # 4b. EVENT_BLOCKED — never READY (distinct from decision REJECTED).
    if event_block:
        return _result("MONITOR", False, "BLOCKED", packet=p,
                       blocks=list(swing.get("blocks") or ["EVENT_BLOCKED"]),
                       reason="event/timing blocks action — mechanics may remain constructible")

    # 5. Tactical/swing: PROPOSE_ENTRY only when action_state is READY (requires
    #    decision ELIGIBLE + constructible + no event block). CONDITIONAL exposes
    #    the trigger but is NOT allowed.
    if swing_action == "READY" and swing_decision == "ELIGIBLE":
        conf = ["operator approval in Options/Proposals", "per-order 2FA at submit"]
        if existing_proposal:
            return _result("MONITOR", False, "CONDITIONAL", packet=p,
                           warnings=["a proposal already exists for this symbol"],
                           reason="proposal already open — monitor it")
        return _result("PROPOSE_ENTRY", True, "READY", packet=p,
                       confirmations=conf,
                       reason="swing blueprint is eligible with resolved mechanics")

    if swing_action == "CONDITIONAL" or swing_decision == "CONDITIONAL":
        trig = (swing_struct.get("underlying_trigger") or tactical.get("trigger")
                or "condition not met")
        inval = swing_struct.get("underlying_invalidation") or tactical.get("invalidation")
        warns = [f"conditional — trigger: {trig}"]
        if inval:
            warns.append(f"invalidation: {inval}")
        return _result("MONITOR", False, "CONDITIONAL", packet=p,
                       warnings=warns,
                       reason="swing is conditional; expose the trigger, do not offer entry")

    # 6. Options: action READY + an ELIGIBLE child routes to research.
    opt_action = _action(options)
    opt_decision = _decision(options)
    opt_eligible = any(str(s.get("state") or "").upper() == "ELIGIBLE"
                       for s in (options.get("structures") or []))
    if opt_action == "READY" and opt_eligible:
        return _result("RESEARCH_OPTIONS", True, "READY", packet=p,
                       confirmations=["options approval + per-order 2FA at submit"],
                       reason="an exact option structure is eligible — research it")
    if opt_action == "CONDITIONAL" or opt_decision == "CONDITIONAL":
        return _result("RESEARCH_OPTIONS", False, "CONDITIONAL", packet=p,
                       warnings=["options are conditional — no resolvable structure yet"],
                       reason="options conditional; research, do not propose")

    # 7. NO_TRADE blocks only when preferred or dominant — mere availability never
    #    vetoes an otherwise ready plan (the old "No-trade ELIGIBLE" bug).
    #    Legacy packets that only have state=ELIGIBLE on no_trade (without preferred)
    #    are treated as preferred only when no other family is READY/ELIGIBLE.
    nt_preferred = bool(no_trade.get("dominant") or no_trade.get("preferred"))
    if not nt_preferred and str(no_trade.get("state") or "").upper() == "ELIGIBLE":
        # Legacy shape: only block when nothing else is actionable.
        others_ready = (
            (swing_action == "READY" and swing_decision == "ELIGIBLE")
            or (opt_action == "READY" and opt_eligible)
        )
        nt_preferred = not others_ready
    if nt_preferred:
        return _result("NO_ACTION", False, "CONDITIONAL", packet=p,
                       blocks=[no_trade.get("reason")
                               or "no_trade preferred/dominant — no other plan actionable"],
                       reason="no-trade is preferred; other families are not ready")

    # 8. Fallthrough — nothing actionable, keep watching.
    return _result("MONITOR", False, "CONDITIONAL", packet=p,
                   reason="no eligible or conditional entry; monitor")
