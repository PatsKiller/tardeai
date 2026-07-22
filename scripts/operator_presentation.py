#!/usr/bin/env python3
"""operator_presentation.py — THE single server-side presentation object.

Header, family tiles, CTA, mechanics and verification panel all derive from
this one classification. The absolute rule it enforces:

    No verified ticket → NO current mechanics. Not partial mechanics, not a
    lone target, not a distant trigger, not an optimistic header.

Pure function of (packet, action_policy). Verification never renders null —
every packet classifies into exactly one state:

    VERIFIED · DETERMINISTIC_FAIL · UNVERIFIED_LEGACY · VALIDATION_RUNNING ·
    REVIEW_SPLIT · STALE_AFTER_VALIDATION · NO_ACTIONABLE_TICKET · BLOCKED
"""
from __future__ import annotations

PRESENTATION_VERSION = "1.0.0"

_NO_MECH_HEADERS = {"BLOCKED", "NO TRADE", "MISSED ENTRY", "UNVERIFIED"}


def build(packet: dict, action_policy: dict | None = None) -> dict:
    p = packet or {}
    ap = action_policy or {}
    tr = p.get("ticket_review") or {}
    rec = tr.get("reconciled") or {}
    cap = p.get("current_actionable_plan")
    tv = (cap or {}).get("ticket_validation") or {}
    validated_any = bool(tr.get("tickets_validated"))
    own = p.get("ownership") or {}
    held = bool(own.get("held"))
    ev = ((p.get("event_state") or {}).get("earnings") or {})
    event_blocked = "BLOCK" in str(ev.get("state", "")).upper() \
        or str(ap.get("state", "")).upper() == "BLOCKED"
    fams = p.get("plan_families") or {}
    nt = fams.get("no_trade") or {}
    no_trade_pref = bool(nt.get("preferred") or nt.get("dominant"))
    sw = (fams.get("swing") or {})
    sw_struct = (sw.get("structures") or [{}])[0]
    entry_state = str(sw_struct.get("entry_state") or "").upper()

    # ── verification classification (never null) ─────────────────────────────
    if not tr and not cap:
        verification = "UNVERIFIED_LEGACY"
    elif rec.get("state") == "DETERMINISTIC_FAIL" or tv.get("state") == "FAIL":
        verification = "DETERMINISTIC_FAIL"
    elif rec.get("state") == "STALE_AFTER_REVIEW":
        verification = "STALE_AFTER_VALIDATION"
    elif rec.get("state") == "REVIEW_SPLIT":
        verification = "REVIEW_SPLIT"
    elif cap is None and validated_any:
        verification = "DETERMINISTIC_FAIL"      # only candidate was stripped
    elif cap is None:
        verification = "NO_ACTIONABLE_TICKET"
    elif tv.get("state") == "PASS":
        verification = "VERIFIED"
    elif tv:
        verification = "REVIEW_SPLIT" if tv.get("state") == "REVIEW_REQUIRED" else "UNVERIFIED_LEGACY"
    else:
        verification = "UNVERIFIED_LEGACY"

    # ── the universal display gate ───────────────────────────────────────────
    display_mech = (
        verification == "VERIFIED"
        and cap is not None
        and not event_blocked
        and not no_trade_pref
        and entry_state not in ("MISSED_ENTRY", "INVALIDATED")
        and not held        # held → position-management ticket required (none yet)
    )

    # ── header state (must agree with family tiles + policy) ─────────────────
    ap_state = str(ap.get("state", "")).upper()
    if held:
        header = "MANAGE POSITION"
        header_note = "held position — starter-entry mechanics suppressed; position-management ticket required"
    elif event_blocked:
        header = "BLOCKED"
        header_note = "event risk blocks new entries"
    elif verification in ("UNVERIFIED_LEGACY",):
        header = "UNVERIFIED"
        header_note = "UNVERIFIED — REBUILD REQUIRED (packet predates the oversight schema)"
    elif verification == "DETERMINISTIC_FAIL":
        header = "WAIT"
        header_note = "ticket failed deterministic validation — no current entry"
    elif no_trade_pref:
        header = "NO TRADE"
        header_note = "no-trade is preferred — no constructive current mechanics"
    elif entry_state == "MISSED_ENTRY":
        header = "WAIT"
        header_note = "entry missed — no current entry, do not chase"
    elif display_mech and bool(ap.get("allowed")) and ap.get("action") == "PROPOSE_ENTRY":
        header = "READY"
        header_note = "verified released ticket"
    else:
        header = "WAIT"
        header_note = ap.get("reason") or "conditions not met"

    proposal_allowed = bool(rec.get("proposal_allowed")) and bool(ap.get("allowed")) \
        and header == "READY"

    # ── mechanics: populated ONLY through the gate ───────────────────────────
    if display_mech:
        mech = {k: cap.get(k) for k in ("entry_zone", "limit_price", "stop_price",
                                        "targets", "risk_reward", "trigger",
                                        "invalidation", "structure", "entry_mode")}
    else:
        mech = {k: None for k in ("entry_zone", "limit_price", "stop_price",
                                  "targets", "risk_reward", "trigger",
                                  "invalidation", "structure", "entry_mode")}
    # non-current values move to labelled sections, never "current"
    non_current = {}
    if not display_mech:
        prev = p.get("previous_plan")
        if prev:
            non_current["previous_plan"] = prev
        ws = p.get("watch_scenarios") or []
        if ws:
            non_current["watch_conditions"] = ws
        if cap and verification != "VERIFIED":
            non_current["rejected_candidate"] = {
                "structure": cap.get("structure"),
                "reason": (tv.get("hard_failures") or ["validation incomplete"])[0]}

    # family tile words must agree with the header (SWBI: header WAIT vs tile READY)
    tile_overrides = {}
    if header != "READY":
        sw_action = str(sw_struct.get("action_state", "")).upper()
        if sw_action == "READY" or str(sw.get("state", "")).upper() == "ELIGIBLE":
            tile_overrides["swing"] = ("WAIT", "header governs: ticket not released")

    return {
        "presentation_version": PRESENTATION_VERSION,
        "verification_state": verification,
        "verification_detail": rec.get("detail") or (tv.get("hard_failures") or [None])[0],
        "display_current_mechanics": display_mech,
        "header_state": header,
        "header_note": header_note,
        "proposal_allowed": proposal_allowed,
        "mechanics": mech,
        "non_current": non_current,
        "tile_overrides": tile_overrides,
        "held": held,
        "event_blocked": event_blocked,
        "no_trade_preferred": no_trade_pref,
        "entry_state": entry_state or None,
        "ticket_hash": tv.get("ticket_hash"),
        "reviews": {k: (v or {}).get("verdict") for k, v in (tr.get("reviews") or {}).items()
                    if isinstance(v, dict) and not k.startswith("_")},
    }
