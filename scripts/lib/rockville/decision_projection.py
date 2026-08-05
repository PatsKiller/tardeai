"""Canonical Watch decision projection (Rockville card v2).

One primary state. Mechanics only when state is READY or MANAGING and gate opens.
DETERMINISTIC_FAIL is never rendered as WAIT.
LLM cannot convert deterministic failure to READY/WAIT/proposal-eligible.
"""
from __future__ import annotations

from typing import Any

PROJECTION_VERSION = "rockville-watch-decision-v1.0.0"

PRIMARY_STATES = frozenset({
    "READY",
    "WAIT",
    "REVIEW_PENDING",
    "STALE",
    "AVOID",
    "BLOCKED",
    "DETERMINISTIC_FAIL",
    "DATA_UNAVAILABLE",
    "MANAGING",
})

# States that must expose ZERO current trade mechanics
INVALID_MECHANICS_STATES = frozenset({
    "STALE",
    "AVOID",
    "BLOCKED",
    "DETERMINISTIC_FAIL",
    "DATA_UNAVAILABLE",
    "REVIEW_PENDING",
})

MECH_KEYS = (
    "entry_zone",
    "limit_price",
    "stop_price",
    "targets",
    "risk_reward",
    "trigger",
    "invalidation",
    "structure",
    "entry_mode",
    "risk_per_share",
)


def _upper(v: Any) -> str:
    return str(v or "").strip().upper()


def _first_blockers(packet: dict, quality: dict | None = None) -> list[dict]:
    out: list[dict] = []
    tr = packet.get("ticket_review") or {}
    rec = tr.get("reconciled") or {}
    cap = packet.get("current_actionable_plan")
    tv = (cap or {}).get("ticket_validation") or {}
    for h in (tv.get("hard_failures") or rec.get("hard_failures") or []):
        out.append({"code": "TICKET_VALIDATION", "message": str(h), "source": "ticket_validation"})
    q = quality or packet.get("quality_admission") or packet.get("quality") or {}
    for b in (q.get("blockers") or q.get("reasons") or []):
        if isinstance(b, dict):
            out.append({
                "code": str(b.get("code") or "QUALITY"),
                "message": str(b.get("message") or b.get("detail") or b),
                "source": "quality_admission",
            })
        else:
            out.append({"code": "QUALITY", "message": str(b), "source": "quality_admission"})
    # common float/ATR narrative fields
    for key in ("float_blocker", "atr_blocker", "admission_blockers"):
        val = q.get(key)
        if isinstance(val, list):
            for item in val:
                out.append({"code": key.upper(), "message": str(item), "source": "quality_admission"})
        elif val:
            out.append({"code": key.upper(), "message": str(val), "source": "quality_admission"})
    # dedupe by message
    seen = set()
    deduped = []
    for b in out:
        k = b["message"]
        if k in seen:
            continue
        seen.add(k)
        deduped.append(b)
    return deduped


def classify_primary_state(
    packet: dict,
    action_policy: dict | None = None,
    *,
    quality: dict | None = None,
) -> str:
    """Pure deterministic primary state. Never lets LLM override."""
    p = packet or {}
    ap = action_policy or {}
    tr = p.get("ticket_review") or {}
    rec = tr.get("reconciled") or {}
    cap = p.get("current_actionable_plan")
    tv = (cap or {}).get("ticket_validation") or {}
    own = p.get("ownership") or {}
    held = bool(own.get("held") or p.get("held"))
    ev = ((p.get("event_state") or {}).get("earnings") or {})
    event_blocked = "BLOCK" in _upper(ev.get("state")) or _upper(ap.get("state")) == "BLOCKED"
    q = quality or p.get("quality_admission") or p.get("quality") or {}
    q_state = _upper(q.get("state") or q.get("admission") or q.get("verdict"))
    rec_state = _upper(rec.get("state"))
    tv_state = _upper(tv.get("state"))
    ap_state = _upper(ap.get("state"))
    data_state = _upper(p.get("data_state") or (p.get("freshness") or {}).get("state"))

    if held:
        return "MANAGING"
    if data_state in ("UNAVAILABLE", "DATA_UNAVAILABLE", "MISSING"):
        return "DATA_UNAVAILABLE"
    if event_blocked or ap_state == "BLOCKED":
        return "BLOCKED"
    if q_state in ("FAIL", "FAILED", "REJECTED", "EXCLUDED") or bool(q.get("blockers")):
        # quality admission fail is DETERMINISTIC_FAIL when ticket also fails or no pass
        if tv_state == "FAIL" or rec_state == "DETERMINISTIC_FAIL" or not (tv_state == "PASS"):
            return "DETERMINISTIC_FAIL"
    if rec_state == "DETERMINISTIC_FAIL" or tv_state == "FAIL":
        return "DETERMINISTIC_FAIL"
    if rec_state == "STALE_AFTER_REVIEW" or data_state == "STALE" or ap_state == "STALE":
        return "STALE"
    if tv_state == "REVIEW_REQUIRED" or rec_state == "REVIEW_SPLIT" or ap_state == "REVIEW_PENDING":
        return "REVIEW_PENDING"
    if _upper((p.get("plan_families") or {}).get("no_trade", {}).get("preferred")) in ("TRUE", "1") \
            or bool(((p.get("plan_families") or {}).get("no_trade") or {}).get("preferred")):
        return "AVOID"
    if (
        tv_state == "PASS"
        and cap is not None
        and bool(ap.get("allowed"))
        and _upper(ap.get("action")) in ("PROPOSE_ENTRY", "READY", "PROPOSE")
        and bool(rec.get("proposal_allowed", True))
    ):
        return "READY"
    if not tr and not cap and not q:
        return "DATA_UNAVAILABLE"
    return "WAIT"


def _meaning(state: str) -> str:
    return {
        "READY": "Verified setup — proposal review allowed",
        "WAIT": "Watching for confirmation — no executable ticket",
        "REVIEW_PENDING": "Deterministic review still pending",
        "STALE": "Inputs or plan are stale — not current",
        "AVOID": "No-trade preferred — stand aside",
        "BLOCKED": "Risk/event block — no new entries",
        "DETERMINISTIC_FAIL": "NO TRADE MECHANICS — quality or ticket validation failed",
        "DATA_UNAVAILABLE": "Required data missing — cannot decide",
        "MANAGING": "Held position — management, not starter entry",
    }.get(state, state)


def _allowed_action(state: str) -> str:
    return {
        "READY": "REVIEW PROPOSAL",
        "WAIT": "SET CONDITION ALERT / OBSERVE",
        "REVIEW_PENDING": "VIEW REVIEW STATUS",
        "STALE": "REFRESH INPUTS",
        "AVOID": "VIEW BLOCKERS / STAND ASIDE",
        "BLOCKED": "VIEW BLOCKERS",
        "DETERMINISTIC_FAIL": "NO TRADE ACTION",
        "DATA_UNAVAILABLE": "REFRESH INPUTS",
        "MANAGING": "VIEW POSITION PLAN",
    }.get(state, "OBSERVE")


def project_watch_decision(
    packet: dict,
    action_policy: dict | None = None,
    *,
    quality: dict | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Project one canonical decision card payload.

    Invariants:
      - one primary_state
      - proposal_allowed only when READY
      - current_mechanics_visible only when READY or MANAGING (and gate opens)
      - DETERMINISTIC_FAIL never maps to WAIT
    """
    p = packet or {}
    ap = action_policy or p.get("action_policy") or {}
    sym = (symbol or p.get("symbol") or "").upper()
    state = classify_primary_state(p, ap, quality=quality)
    assert state in PRIMARY_STATES

    blockers = _first_blockers(p, quality)
    proposal_allowed = state == "READY"
    # LLM cannot force proposal
    if p.get("llm_override_state") or p.get("reflective_force_ready"):
        # ignore — authority stays deterministic
        pass

    current_mechanics_visible = state in ("READY", "MANAGING") and proposal_allowed if state == "READY" else state == "MANAGING"
    if state in INVALID_MECHANICS_STATES:
        current_mechanics_visible = False
        proposal_allowed = False

    cap = p.get("current_actionable_plan") if current_mechanics_visible else None
    current_mechanics = None
    history = None
    wait_contract = None

    if current_mechanics_visible and state == "READY" and isinstance(cap, dict):
        current_mechanics = {k: cap.get(k) for k in MECH_KEYS}
    elif state == "MANAGING":
        pos = p.get("position") or p.get("ownership") or {}
        current_mechanics = {
            "shares": pos.get("shares") or pos.get("qty"),
            "cost_basis": pos.get("cost_basis") or pos.get("avg_cost"),
            "mark": pos.get("mark") or pos.get("last"),
            "protection_state": pos.get("protection_state"),
            "management_stop": pos.get("stop") or pos.get("management_stop"),
        }
    else:
        # history only
        hist: dict[str, Any] = {"label": "NOT CURRENT", "note": "Historical / rejected mechanics — not actionable"}
        if isinstance(p.get("current_actionable_plan"), dict):
            hist["rejected_candidate"] = {
                k: p["current_actionable_plan"].get(k)
                for k in ("trigger", "invalidation", "entry_zone", "stop_price", "targets")
            }
        if p.get("previous_plan"):
            hist["previous_plan"] = p["previous_plan"]
        if p.get("watch_scenarios"):
            hist["watch_conditions"] = p["watch_scenarios"]
        history = hist

    if state == "WAIT":
        wait_contract = {
            "what_must_happen": (ap.get("reason") or p.get("wait_condition") or "Confirmation condition not met"),
            "what_must_remain_true": p.get("wait_must_remain") or [],
            "what_would_invalidate": p.get("wait_invalidation") or [],
            "next_review": p.get("next_review_at") or ap.get("next_review"),
            "executable": False,
        }

    # visibility flags for regression tests
    flags = {
        "trigger_visible": False,
        "entry_visible": False,
        "stop_or_invalidation_visible": False,
        "targets_visible": False,
        "risk_reward_visible": False,
    }
    if current_mechanics_visible and current_mechanics and state == "READY":
        flags = {
            "trigger_visible": current_mechanics.get("trigger") is not None,
            "entry_visible": current_mechanics.get("entry_zone") is not None or current_mechanics.get("limit_price") is not None,
            "stop_or_invalidation_visible": current_mechanics.get("stop_price") is not None or current_mechanics.get("invalidation") is not None,
            "targets_visible": current_mechanics.get("targets") is not None,
            "risk_reward_visible": current_mechanics.get("risk_reward") is not None,
        }

    return {
        "schema_version": "watch_decision.v1",
        "symbol": sym,
        "primary_state": state,
        "operator_meaning": _meaning(state),
        "allowed_action_now": _allowed_action(state),
        "proposal_allowed": proposal_allowed,
        "current_mechanics_visible": current_mechanics_visible,
        "selected_strategy_family": (p.get("selected_family") or ap.get("family")),
        "last_state_change_at": p.get("state_changed_at"),
        "last_state_change_reason": p.get("state_change_reason") or (blockers[0]["message"] if blockers else None),
        "next_deterministic_review_condition": (
            "Refresh float and volatility inputs, then rerun deterministic validation"
            if state == "DETERMINISTIC_FAIL"
            else ap.get("next_review")
        ),
        "blockers": blockers,
        "supporting_drivers": list(p.get("supporting_drivers") or [])[:3],
        "conflicting_drivers": list(p.get("conflicting_drivers") or [])[:3],
        "blocking_drivers": [b["message"] for b in blockers][:3],
        "current_mechanics": current_mechanics,
        "wait_contract": wait_contract,
        "history_mechanics_not_current": history,
        "visibility": flags,
        "provenance": {
            "source": "rockville.decision_projection",
            "projection_version": PROJECTION_VERSION,
            "input_hashes": {
                "ticket_hash": ((p.get("current_actionable_plan") or {}).get("ticket_validation") or {}).get("ticket_hash"),
                "packet_id": p.get("packet_id") or p.get("id"),
            },
        },
    }


def assert_no_mechanics_on_invalid(decision: dict) -> None:
    """Raise if an invalid state exposes current mechanics (regression guard)."""
    state = decision.get("primary_state")
    if state in INVALID_MECHANICS_STATES:
        if decision.get("current_mechanics_visible"):
            raise AssertionError(f"{state} must not set current_mechanics_visible")
        if decision.get("proposal_allowed"):
            raise AssertionError(f"{state} must not allow proposals")
        vis = decision.get("visibility") or {}
        for k, v in vis.items():
            if v:
                raise AssertionError(f"{state} must not expose {k}")
        if decision.get("primary_state") == "DETERMINISTIC_FAIL" and state == "WAIT":
            raise AssertionError("DETERMINISTIC_FAIL must not be WAIT")
