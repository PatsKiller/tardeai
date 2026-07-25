#!/usr/bin/env python3
"""strategy_ticket_validator.py — MANDATORY deterministic final-ticket gate.

HARD AUTHORITY: runs after construction, before persistence/display/proposal.
Cannot be disabled; an LLM may never override a hard failure here. Pure — no
network, no DB, no model. The FATN fabrication (current $4.75, displayed entry
$6.76 / stop $5.94 / target $8.40) is this module's permanent regression
fixture: it must HARD FAIL on proximity and mode-mutation checks.

    validate_ticket(symbol, family, candidate_ticket, current_facts,
                    technical_snapshot=None, event_state=None, ownership=None,
                    risk_policy=None) -> dict (state PASS|FAIL|REVIEW_REQUIRED)

A hard failure prevents: persistence as current_actionable_plan, proposal
eligibility, READY, and current-mechanics rendering. The candidate is retained
in audit evidence only.
"""
from __future__ import annotations

import hashlib
import json
import math

VALIDATOR_VERSION = "1.1.0"
RR_TOLERANCE = 0.15               # recomputed vs displayed R:R
PRICE_TOLERANCE = 0.01
CHASE_MAX_PCT = 1.5               # entry farther than this from price → not current
CHASE_MAX_ATR = 0.5
TRIGGER_MAX_PCT = 8.0             # min(8%, 2 ATR) — governed actionability ceiling
TRIGGER_MAX_ATR = 2.0


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def ticket_hash(ticket: dict) -> str:
    keys = ("structure", "entry_mode", "entry_zone", "limit_price", "stop_price",
            "targets", "risk_reward", "trigger", "invalidation", "entry_state")
    return hashlib.sha256(json.dumps({k: ticket.get(k) for k in keys},
                                     sort_keys=True, default=str).encode()).hexdigest()[:16]


def facts_hash(facts: dict) -> str:
    keys = ("symbol", "live_price", "enriched_price", "atr")
    return hashlib.sha256(json.dumps({k: facts.get(k) for k in keys},
                                     sort_keys=True, default=str).encode()).hexdigest()[:16]


def _quality_admission(family: str, ticket: dict, facts: dict,
                       technical_snapshot: dict | None, ownership) -> dict:
    """Evaluate the model-free instrument/strategy admission policy.

    Importing inside the function keeps this validator independently usable in
    narrow test harnesses while still failing closed when the policy module
    itself cannot be evaluated.
    """
    try:
        import watch_quality_policy as quality
        return quality.evaluate_admission(
            facts,
            technical_snapshot=technical_snapshot,
            ticket=ticket,
            family=family,
            ownership=ownership,
        )
    except Exception as exc:
        return {
            "policy_version": "watch-quality-admission-v1",
            "state": "RESEARCH_ONLY",
            "new_entry_allowed": False,
            "management_only": False,
            "family": str(family or "").upper() or None,
            "reasons": [f"quality admission unavailable: {type(exc).__name__}: {str(exc)[:120]}"],
            "hard_failures": [],
            "warnings": ["quality admission unavailable — fail closed to research only"],
            "authority": "deterministic admission only; models cannot override",
        }


def validate_ticket(symbol: str, family: str, candidate_ticket: dict,
                    current_facts: dict, technical_snapshot: dict | None = None,
                    event_state=None, ownership=None, risk_policy=None) -> dict:
    t = candidate_ticket or {}
    hard: list[str] = []
    warnings: list[str] = []
    admission = _quality_admission(family, t, current_facts,
                                   technical_snapshot, ownership)
    price = _num(current_facts.get("live_price")) or _num(current_facts.get("enriched_price"))
    atr = _num(current_facts.get("atr"))
    entry = _num(t.get("limit_price"))
    stop = _num(t.get("stop_price"))
    targets = [x for x in (_num(v) for v in (t.get("targets") or [])) if x is not None]
    target = targets[0] if targets else None
    zone = t.get("entry_zone") or [None, None]
    zlo, zhi = (_num(zone[0]) if len(zone) > 0 else None), (_num(zone[1]) if len(zone) > 1 else None)
    direction_short = family == "BEARISH" or str(t.get("structure", "")).startswith("SHORT")
    is_current = bool(t.get("mechanics_current", True))
    recomputed = {"entry": entry, "stop": stop, "target": target,
                  "risk_per_share": None, "reward_per_share": None, "risk_reward": None,
                  "distance_to_entry_pct": None, "distance_to_entry_atr": None}

    if not is_current or not any(v is not None for v in (entry, stop, target)):
        # No current mechanics claimed: preserve the quality classification in
        # audit, but do not turn a non-actionable record into a ticket failure.
        return _result("PASS", hard, warnings, recomputed, t, current_facts,
                       quality_admission=admission,
                       note="no current mechanics claimed")

    # ── deterministic quality admission ──────────────────────────────────────
    # A research-only or quarantined instrument may remain visible, but it may
    # not carry current new-entry mechanics.  Existing holdings are management
    # surfaces only; the admission record explicitly denies a new add.
    if admission.get("state") == "QUARANTINED":
        reasons = admission.get("hard_failures") or admission.get("reasons") or []
        hard.extend([f"quality admission: {reason}" for reason in reasons[:5]])
    elif not admission.get("new_entry_allowed", False):
        reasons = admission.get("warnings") or admission.get("reasons") or []
        hard.append("quality admission: instrument is RESEARCH_ONLY; current entry mechanics are withheld")
        hard.extend([f"quality admission: {reason}" for reason in reasons[:4]])

    # ── numeric sanity ───────────────────────────────────────────────────────
    for name, v in (("entry/limit", entry), ("stop", stop), ("target", target)):
        if v is None:
            hard.append(f"{name} missing or non-finite on a current-mechanics ticket")
        elif v <= 0:
            hard.append(f"{name} is non-positive ({v})")
    if price is None:
        hard.append("no current price in facts — a current ticket cannot be validated")
    if hard:
        return _result("FAIL", hard, warnings, recomputed, t, current_facts,
                       quality_admission=admission)

    # ── ordering invariants ──────────────────────────────────────────────────
    if zlo is not None and zhi is not None and zlo > zhi + PRICE_TOLERANCE:
        hard.append(f"entry zone inverted ({zlo} > {zhi})")
    if direction_short:
        if not (target < entry < stop):
            hard.append(f"short ordering violated: need target<entry<stop, got "
                        f"{target}/{entry}/{stop}")
    else:
        if not (stop < entry <= target + PRICE_TOLERANCE):
            hard.append(f"long ordering violated: need stop<entry<=target, got "
                        f"{stop}/{entry}/{target}")

    # ── R:R recomputation ────────────────────────────────────────────────────
    risk = (stop - entry) if direction_short else (entry - stop)
    reward = (entry - target) if direction_short else (target - entry)
    recomputed.update(risk_per_share=round(risk, 4), reward_per_share=round(reward, 4))
    if risk <= 0:
        hard.append(f"non-positive risk per share ({risk:.4f})")
    else:
        rr = reward / risk
        recomputed["risk_reward"] = round(rr, 2)
        shown = _num(t.get("risk_reward"))
        if shown is not None and abs(shown - rr) > RR_TOLERANCE:
            hard.append(f"R:R mismatch: displayed {shown} vs recomputed {rr:.2f}")

    # ── proximity / actionability ────────────────────────────────────────────
    dist_abs = abs(entry - price)
    dist_pct = 100.0 * dist_abs / price
    dist_atr = (dist_abs / atr) if atr else None
    recomputed.update(distance_to_entry_pct=round(dist_pct, 2),
                      distance_to_entry_atr=round(dist_atr, 2) if dist_atr is not None else None)
    mode = str(t.get("entry_mode") or "").upper()
    entry_state = str(t.get("entry_state") or "").upper()
    if mode == "BREAKOUT" or entry_state.endswith("BREAKOUT"):
        if entry < price - PRICE_TOLERANCE:
            warnings.append("breakout entry below current price — verify trigger already ran")
        if dist_pct > TRIGGER_MAX_PCT or (dist_atr is not None and dist_atr > TRIGGER_MAX_ATR):
            hard.append(f"breakout trigger {dist_pct:.1f}%"
                        f"{f'/{dist_atr:.1f} ATR' if dist_atr is not None else ''} from current "
                        f"price exceeds min({TRIGGER_MAX_PCT}%, {TRIGGER_MAX_ATR} ATR) — "
                        f"FUTURE SCENARIO, not current mechanics")
        if not t.get("independent_of_pullback_plan") and t.get("proposal_tag"):
            hard.append("breakout ticket inherits a pullback plan identity — "
                        "a missed plan must not mutate into a different strategy")
    else:  # pullback / reversal / continuation entries must be NEAR price
        in_zone = zlo is not None and zhi is not None and zlo - PRICE_TOLERANCE <= price <= zhi + PRICE_TOLERANCE
        within_chase = dist_pct <= CHASE_MAX_PCT or (dist_atr is not None and dist_atr <= CHASE_MAX_ATR)
        if not in_zone and not within_chase:
            hard.append(f"entry {entry} is {dist_pct:.1f}% from current price {price} "
                        f"and price is outside the entry zone — missed/distant entry "
                        f"cannot populate current mechanics")
    if entry_state in ("MISSED_ENTRY", "INVALIDATED"):
        hard.append(f"entry_state={entry_state} ticket still claims current mechanics")

    # ── technical/event context ──────────────────────────────────────────────
    if technical_snapshot:
        fresh = str(technical_snapshot.get("overall_freshness", ""))
        if fresh == "FAILED":
            warnings.append("technical snapshot FAILED — review required")
    ev = str(getattr(event_state, "state", None) or (event_state or {}).get("state", "")
             if isinstance(event_state, (dict,)) or event_state is None else event_state)
    if "BLOCK" in ev.upper():
        hard.append(f"event state {ev} blocks a current-entry ticket")

    state = "FAIL" if hard else ("REVIEW_REQUIRED" if warnings else "PASS")
    return _result(state, hard, warnings, recomputed, t, current_facts,
                   quality_admission=admission)


def _result(state, hard, warnings, recomputed, ticket, facts,
            quality_admission=None, note=None):
    out = {"state": state, "hard_failures": hard, "warnings": warnings,
           "recomputed": recomputed,
           "quality_admission": quality_admission or {},
           "ticket_hash": ticket_hash(ticket or {}),
           "facts_hash": facts_hash(facts or {}),
           "validator_version": VALIDATOR_VERSION}
    if note:
        out["note"] = note
    return out
