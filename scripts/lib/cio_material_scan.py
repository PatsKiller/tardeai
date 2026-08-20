"""Production material scanner — auto office state, no manual holdings args.

Evaluates:
  verified book change, cash/capital-plan change, re-entry transition,
  decision freshness transition, research/risk/concentration change, due defer.

First run captures a baseline snapshot and does **not** treat every holding
as POSITION_OPENED.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_alex_telegram import (
    apply_actionability,
    due_defers,
    rejected_unchanged,
)
from scripts.lib.cio_holdings_delta import diff_holdings
from scripts.lib.cio_material_publisher import publish_material_decision
from scripts.lib.cio_office_state import (
    AUTHORITY,
    cash_posture,
    classify_reentry_rows,
    compact_holdings_rows,
    load_live_office,
    save_holdings_snapshot,
    save_office_state,
)
from scripts.lib.cio_telegram_transport import cio_delivery_mode

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RECEIPT_PATH = PROJECT_ROOT / "data" / "audit" / "cio_material_scan_last.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _decision(
    *,
    decision_id: str,
    symbol: str,
    action: str,
    why: str,
    counter: str,
    change: str,
    delta: float = 0.0,
    urgency: str = "normal",
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    body = {
        "decision_id": decision_id,
        "symbol": symbol,
        "action": action,
        "stance": action,
        "stance_code": action,
        "why_now": why,
        "counter_thesis": counter,
        "what_changes_call": change,
        "recommended_delta_usd": delta,
        "delta_usd": delta,
        "urgency": urgency,
        "status": "open",
        "material_hold": action in {"HOLD", "WAIT", "HOLD_CASH", "NO_ACTION"},
    }
    if extra:
        body.update(extra)
    body.setdefault("decision_input_digest", _digest({
        "id": decision_id, "action": action, "why": why, "delta": delta,
    }))
    body.setdefault("decision_evidence_digest", _digest(extra or {"symbol": symbol}))
    apply_actionability(body)
    return body


def _holdings_decisions(events: list[dict[str, Any]], *, baseline: bool) -> list[dict[str, Any]]:
    if baseline:
        return []
    out: list[dict[str, Any]] = []
    for ev in events:
        kind = ev.get("event")
        sym = str(ev.get("symbol") or "")
        acct = ev.get("account") or ev.get("to_account") or ""
        if kind == "POSITION_OPENED":
            out.append(_decision(
                decision_id=f"dec_open_{sym}_{acct or 'book'}",
                symbol=sym,
                action="RESEARCH",
                why=(
                    f"Verified book shows a new {sym} sleeve ({acct}). "
                    "Purchase is not claimed without lot/ACATS evidence."
                ),
                counter="Could be an account transfer, residual lot, or sync catch-up.",
                change="Lot history or ACATS evidence arrives, or the sleeve disappears.",
                extra={"event": kind, "account": acct, "value_usd": ev.get("value_usd")},
            ))
        elif kind == "ACCOUNT_TRANSFER_DETECTED":
            out.append(_decision(
                decision_id=f"dec_xfer_{sym}_{acct or 'book'}",
                symbol=sym,
                action="RESEARCH",
                why=(
                    f"Account transfer detected for {sym} → {acct}. "
                    "Not a new purchase."
                ),
                counter="Could be a same-day buy plus close on another account.",
                change="Cost-basis / ACATS evidence confirms or refutes transfer.",
                extra={"event": kind, "purchase_claimed": False},
            ))
        elif kind == "POSITION_CLOSED":
            out.append(_decision(
                decision_id=f"dec_close_{sym}_{acct or 'book'}",
                symbol=sym,
                action="RESEARCH",
                why=f"Verified book no longer shows {sym} ({acct}).",
                counter="Could be a transfer out or a pricing/sync hole.",
                change="Sleeve reappears or sale evidence is confirmed.",
                extra={"event": kind, "prior_value_usd": ev.get("prior_value_usd")},
            ))
        elif kind == "POSITION_SIZE_CHANGED_MATERIAL":
            out.append(_decision(
                decision_id=f"dec_size_{sym}_{acct or 'book'}",
                symbol=sym,
                action="RESEARCH",
                why=(
                    f"{sym} market value changed materially "
                    f"{ev.get('prior_value_usd')} → {ev.get('value_usd')}."
                ),
                counter="Mark-to-market move, not necessarily a trade.",
                change="Share count confirms a real size change vs price-only drift.",
                extra={"event": kind, "delta_usd": ev.get("delta_usd")},
            ))
    return out


def _cash_decision(plan: dict[str, Any], reclass: dict[str, Any]) -> dict[str, Any]:
    cash = cash_posture(plan)
    status = str(cash.get("cash_posture_status") or "UNKNOWN")
    investable = cash.get("cash_investable_usd")
    reserve = cash.get("cash_reserved_usd")
    deploy = cash.get("net_recommended_deploy_usd")
    act_now = int(cash.get("act_now_count") or 0)
    ready_n = len(reclass.get("ready") or [])
    uses_ready = ready_n > 0 and act_now > 0
    ranked = []
    for row in (cash.get("new_positions") or [])[:8]:
        if isinstance(row, dict) and row.get("symbol"):
            ranked.append(f"{row.get('symbol')} ${float(row.get('amount_usd') or 0):,.0f} ({row.get('note') or row.get('source') or 'candidate'})")
    if uses_ready and status == "ABOVE_BAND":
        action = "DEPLOY_CASH"
        why = (
            f"Cash {status}: investable ${float(investable or 0):,.0f}, reserve "
            f"${float(reserve or 0):,.0f}, recommended deploy ${float(deploy or 0):,.0f}. "
            f"{ready_n} re-entry names READY and {act_now} ACT_NOW decisions."
        )
        change = "Cash falls into band, READY names fail, or freshness goes STALE."
    else:
        action = "HOLD_CASH"
        why = (
            f"HOLD CASH / WAIT. Cash {status}: total ${float(cash.get('cash_total_usd') or 0):,.0f}, "
            f"investable ${float(investable or 0):,.0f}, reserve ${float(reserve or 0):,.0f}, "
            f"recommended deploy ${float(deploy or 0):,.0f} / raise "
            f"${float(cash.get('net_recommended_raise_usd') or 0):,.0f}. "
            f"Re-entry READY={ready_n} NEAR={len(reclass.get('near') or [])} "
            f"WAIT={len(reclass.get('wait') or [])}. ACT_NOW={act_now}. "
            "No force-deploy while uses are not ACT_NOW."
        )
        if ranked:
            why += " Ranked candidate uses (not authorized): " + "; ".join(ranked[:5]) + "."
        change = "A READY re-entry or concentration ACT_NOW survives freshness, or cash re-enters band."
    did = f"dec_cash_{_digest({'status': status, 'action': action, 'd': cash.get('digest')})}"
    act_now_flag = action == "DEPLOY_CASH"
    return _decision(
        decision_id=did,
        symbol="CASH",
        action=action,
        why=why,
        counter="Band math can tolerate more cash if uses stay stale or WASH-blocked.",
        change=change,
        delta=float(deploy or 0) if action == "DEPLOY_CASH" else 0.0,
        urgency="high" if action == "DEPLOY_CASH" else "normal",
        extra={
            "capital": {
                "free_investable": investable,
                "deploy_now": deploy if action == "DEPLOY_CASH" else 0,
                "remain_cash": reserve,
            },
            "cash_posture": cash,
            "reentry_call": reclass.get("call"),
            "act_now": act_now_flag,
            "action_label": "ACT_NOW" if act_now_flag else "NO_ACTION",
            "standing_recommendation": action,
            "current_action": action,
        },
    )


def _governed_reentry_symbols(plan: dict[str, Any]) -> set[str]:
    """Candidate-specific governed RE_ENTER identity.

    Only a symbol whose own capital-plan decision carries stance RE_ENTER
    (produced by an explicit governed verdict) AND a non-blocked ACT_NOW is
    authorized to re-enter. A global ACT_NOW count from an unrelated symbol
    (e.g. SCHD TRIM) never authorizes re-entry for a merely-READY name.
    """
    from scripts.lib.cio_decision_semantics import canonical_act_now
    authorized: set[str] = set()
    for row in plan.get("position_decisions") or []:
        if not isinstance(row, dict):
            continue
        stance = str(row.get("stance_code") or row.get("stance") or "").upper()
        if stance != "RE_ENTER":
            continue
        act_now, blocking = canonical_act_now(row)
        if act_now and not blocking:
            authorized.add(str(row.get("symbol") or "").upper())
    return authorized


def _reentry_decision(reclass: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    ready = reclass.get("ready") or []
    near = reclass.get("near") or []
    # Candidate-specific governed eligibility only. A global ACT_NOW count from
    # an unrelated decision must NEVER authorize re-entry for a merely-READY
    # name — READY/NEAR/OVERSOLD desk state alone is REVIEW/WAIT.
    governed = _governed_reentry_symbols(plan)
    authorized = [s for s in ready if s in governed]
    if authorized:
        action = "RE_ENTER"
        why = (
            f"Re-entry authorized by candidate-specific governed verdicts: "
            f"{', '.join(authorized[:8])}. Advisory only."
        )
        change = "Governed re-entry verdict is revoked or freshness blocks it."
        delta = float((cash_posture(plan).get("reentry_usd") or 0))
    elif ready or near:
        action = "WAIT"
        why = (
            f"Re-entry WAIT. Desk READY={', '.join(ready[:6]) or 'none'} "
            f"NEAR={', '.join(near[:6]) or 'none'} but no candidate-specific "
            "governed RE_ENTER verdict. Do not chase ready marks without "
            "governed authorization."
        )
        change = "A candidate-specific governed RE_ENTER verdict is produced."
        delta = 0.0
    else:
        action = "WAIT"
        why = (
            f"Re-entry WAIT. READY=0 NEAR={len(near)} WAIT={len(reclass.get('wait') or [])} "
            f"of {reclass.get('n') or 0} desk rows. No governed re-entry verdicts."
        )
        change = "A candidate-specific governed RE_ENTER verdict is produced."
        delta = 0.0
    act_now_flag = action == "RE_ENTER"
    standing = "RE_ENTER" if authorized else "WAIT"
    return _decision(
        decision_id=f"dec_reentry_{_digest({'action': action, 'ready': ready[:12], 'near': near[:12], 'authorized': authorized[:12]})}",
        symbol="REENTRY",
        action=action,
        why=why,
        counter="A subset of WAIT names may be near-trigger on a different desk definition.",
        change=change,
        delta=delta,
        extra={
            "reentry": reclass,
            "act_now": act_now_flag,
            "action_label": "ACT_NOW" if act_now_flag else "NO_ACTION",
            "standing_recommendation": standing,
            "current_action": action,
        },
    )


def _canonical_decisions(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Surface standing capital-plan decisions that are already material.

    Does not invent SCHG as a new buy. Freshness/ACT_NOW is copied honestly.
    """
    out: list[dict[str, Any]] = []
    for row in plan.get("position_decisions") or []:
        if not isinstance(row, dict):
            continue
        stance = str(row.get("stance_code") or row.get("stance") or "").upper()
        if stance not in {"TRIM", "EXIT", "ADD", "RE_ENTER", "ROTATE"}:
            continue
        if row.get("act_now") is False and stance != "TRIM":
            # Weekend/stale: only keep concentration TRIMs as standing context.
            if stance != "TRIM":
                continue
        why = str(row.get("why_now") or "").strip()
        if stance == "TRIM" and "concentration" not in why.lower() and "fire" not in why.lower():
            # Keep the largest concentration TRIMs; skip tiny hygiene trims.
            try:
                if abs(float(row.get("recommended_delta_usd") or 0)) < 10_000:
                    continue
            except (TypeError, ValueError):
                continue
        extra = {
            # Copy catalog identity exactly. Do not invent a local evidence
            # digest — that made signed Telegram buttons fail digest_mismatch
            # when the live catalog is decision_id-only (empty hashes).
            "decision_input_digest": str(row.get("decision_input_digest") or ""),
            "decision_evidence_digest": str(row.get("decision_evidence_digest") or ""),
            "weight_pct": row.get("current_weight_pct") or row.get("weight_pct"),
            "current_value_usd": row.get("current_value_usd"),
            "act_now": row.get("act_now"),
            "actionable": row.get("actionable"),
            "action_label": row.get("action_label"),
            "account": row.get("account"),
            "standing_recommendation": stance,
            # Preserve freshness and any pre-stamped actionability so a blocking
            # state survives the material-scan projection exactly as it does in
            # Command Center / Telegram.
            "freshness": row.get("freshness"),
            "actionability": row.get("actionability"),
        }
        # Canonical classifier, not a local "STALE" substring. A blocking state
        # (DATA_CONFLICT / REVALIDATE / STALE_REFRESH_REQUIRED / STALE / EXPIRED)
        # overrides act_now=True across this projection; a blocked row can never
        # be reclassified as actionable.
        from scripts.lib.cio_decision_semantics import actionability_blocking_state
        blocking = actionability_blocking_state(row)
        if blocking:
            why = f"{why} Blocked by {blocking}; not ACT NOW."
            extra["act_now"] = False
            extra["current_action"] = (
                "DATA_CONFLICT" if blocking == "DATA_CONFLICT" else "REVALIDATE"
            )
            extra["actionability"] = blocking
        elif row.get("act_now") is False:
            extra["current_action"] = "WAIT"
        else:
            extra["current_action"] = stance
        out.append(_decision(
            decision_id=str(row.get("decision_id") or f"dec_{row.get('symbol')}_{stance.lower()}"),
            symbol=str(row.get("symbol") or ""),
            action=stance,
            why=why or f"{stance} {row.get('symbol')}",
            counter=str(row.get("counter_thesis") or "None on record."),
            change=str(row.get("what_changes_call") or "Fresh multi-desk evidence or cash-band change."),
            delta=float(row.get("recommended_delta_usd") or 0),
            urgency="high" if stance in {"TRIM", "EXIT"} else "normal",
            extra=extra,
        ))
    return out


def _freshness_decision(plan: dict[str, Any], prev: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    gate = plan.get("freshness_materiality_gate") if isinstance(plan.get("freshness_materiality_gate"), dict) else {}
    counts = gate.get("counts") if isinstance(gate.get("counts"), dict) else {}
    prev_counts = ((prev or {}).get("freshness_counts") if isinstance(prev, dict) else None) or {}
    if not counts:
        return None
    if prev_counts and counts == prev_counts:
        return None
    if not prev_counts and int(counts.get("ACT_NOW") or 0) == 0:
        # First observation of a fully-stale board is recorded on the cash card.
        return None
    return _decision(
        decision_id=f"dec_fresh_{_digest(counts)}",
        symbol="BOOK",
        action="WAIT",
        why=(
            f"Freshness transition ACT_NOW={counts.get('ACT_NOW')} "
            f"STALE={counts.get('STALE_REFRESH_REQUIRED')} "
            f"WATCH={counts.get('WATCH')} (prior {prev_counts or 'none'})."
        ),
        counter="Weekend/holiday marks can look stale without a real book change.",
        change="Required quote/MV evidence refreshes inside policy age.",
        extra={
            "freshness_counts": counts,
            "prior": prev_counts,
            "act_now": False,
            "standing_recommendation": "WAIT",
            "current_action": "WAIT",
        },
    )


def _latest_dispositions() -> dict[str, Any]:
    try:
        from scripts.api_v3_cio import get_decision_dispositions
        blob = get_decision_dispositions() or {}
        dmap = blob.get("dispositions") or {}
        return dmap if isinstance(dmap, dict) else {}
    except Exception:
        return {}


def _attach_operator_state(decision: dict[str, Any], dispositions: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Stamp latest operator disposition / challenge fields. Fail-soft."""
    if not isinstance(decision, dict):
        return decision
    did = str(decision.get("decision_id") or "")
    dmap = dispositions if dispositions is not None else _latest_dispositions()
    disp = dmap.get(did) if did else None
    if isinstance(disp, dict):
        decision["operator_disposition"] = disp.get("disposition")
        if disp.get("note") is not None:
            decision["operator_note"] = disp.get("note")
        if str(disp.get("disposition") or "").strip().lower() == "reject":
            decision["operator_challenge_status"] = "OPEN"
            decision.setdefault("challenge_review", "DATA_UNAVAILABLE")
    apply_actionability(decision)
    return decision


def _instrument_scan(
    selected: list[dict[str, Any]],
    *,
    at: str,
) -> Optional[dict[str, Any]]:
    """Flag-gated AIF observability hook. Returns None when flags are off.

    OFF (default): exact pre-AIF behavior — nothing is built, appended, or
    returned. ON: builds ContextEnvelope@v1 and/or appends one redacted
    AgentRunTrace@v1 with a single wake_id/trace_id lineage. Fail-soft.
    """
    from scripts.lib.agent_runtime_instrumentation import (
        default_trace_path,
        instrument_material_wake,
    )

    decision_ids = [str(d.get("decision_id") or "") for d in selected]
    decision_ids = [d for d in decision_ids if d]
    wake_id = f"wake_scan_{at}"
    result = instrument_material_wake(
        {"wake_id": wake_id, "selected_decision_ids": decision_ids},
        decision_ids=decision_ids,
        trace_path=default_trace_path(),
    )
    if not result.get("instrumented"):
        return None
    return {
        "wake_id": result["wake_id"],
        "trace_id": result["trace_id"],
        "envelope": result.get("envelope"),
        "trace": result.get("trace"),
        "trace_appended": result.get("trace_appended"),
        "errors": result.get("errors"),
    }


def select_publications(
    candidates: list[dict[str, Any]],
    *,
    max_publish: int = 3,
) -> list[dict[str, Any]]:
    """Prefer book events, then cash, then one standing TRIM. Avoid flood.

    Duplicate TRIM that was REJECTED with unchanged input/evidence digests
    is not selected (empty==empty is the same identity).
    """
    live: list[dict[str, Any]] = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        if rejected_unchanged(c):
            continue
        live.append(c)
    opened = [c for c in live if str(c.get("extra_event") or c.get("event") or "") == "POSITION_OPENED"
              or str(c.get("decision_id") or "").startswith("dec_open_")]
    xfer = [c for c in live if str(c.get("decision_id") or "").startswith("dec_xfer_")]
    cash = [c for c in live if c.get("symbol") == "CASH"]
    reentry = [c for c in live if c.get("symbol") == "REENTRY"]
    trims = [c for c in live if str(c.get("action") or c.get("standing_recommendation") or "").upper() == "TRIM"]
    other = [c for c in live if c not in opened + xfer + cash + reentry + trims]
    ordered = opened + xfer + cash + reentry + trims[:1] + other
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for c in ordered:
        did = str(c.get("decision_id") or "")
        if not did or did in seen:
            continue
        seen.add(did)
        out.append(c)
        if len(out) >= max_publish:
            break
    return out


def material_financial_notify_canary_on() -> bool:
    """Explicit canary for material-scan live Telegram. Default OFF.

    Even when ``--live`` and ``CIO_ONLY_LIVE``, financial-lane publishes stay
    dry unless ``CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY=1``. Situation-notify
    (CIO_SITUATION_NOTIFY) is a separate path — do not conflate.
    """
    import os
    return str(os.environ.get("CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY") or "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def scan_office(
    *,
    dry_run: bool = True,
    office: Optional[dict[str, Any]] = None,
    persist: bool = True,
    max_publish: int = 3,
    notification_gate: bool = True,
) -> dict[str, Any]:
    mode = cio_delivery_mode()
    canary = material_financial_notify_canary_on()
    # Live financial Telegram requires CIO_ONLY_LIVE AND explicit canary (default OFF).
    if not dry_run and (mode != "CIO_ONLY_LIVE" or not canary):
        dry_run = True
    office = office or load_live_office()
    holdings = office.get("holdings") or {}
    prev = office.get("previous_snapshot")
    plan = office.get("capital_plan") or {}
    desk = office.get("reentry") or {}
    prev_state = office.get("previous_office_state")
    baseline = bool(office.get("baseline_needed") or prev is None)

    curr_rows = compact_holdings_rows(holdings if isinstance(holdings, dict) else {})
    prev_rows = (prev or {}).get("holdings") if isinstance(prev, dict) else None
    events = [] if baseline or prev_rows is None else diff_holdings(prev_rows, curr_rows)
    reclass = classify_reentry_rows(desk if isinstance(desk, dict) else {})

    candidates: list[dict[str, Any]] = []
    candidates.extend(_holdings_decisions(events, baseline=baseline))
    if plan.get("ok") is not False:
        candidates.append(_cash_decision(plan, reclass))
        candidates.append(_reentry_decision(reclass, plan))
        candidates.extend(_canonical_decisions(plan))
        fresh = _freshness_decision(plan, prev_state)
        if fresh:
            candidates.append(fresh)

    due = []
    try:
        due = due_defers()
    except Exception:
        due = []
    # Due defers are reopened by cio_defer_revisit (same lineage, revalidate,
    # publish-if-material). The scanner only records the count so we do not
    # double-consume lineage here.

    dispositions = _latest_dispositions()
    for cand in candidates:
        _attach_operator_state(cand, dispositions)

    # Canonical notification decision gate (signal-over-spam). OFF by default is
    # NOT the production posture — it is a parity escape hatch only.
    nd_map: dict[str, dict[str, Any]] = {}
    store = None
    if notification_gate:
        from scripts.lib.cio_notification_signal import (
            DELIVERY_IMMEDIATE,
            NotificationStateStore,
            decide_notification,
            render_cio_card,
        )
        from scripts.lib.cio_office_state import office_state_path
        state_dir = office_state_path().parent
        store = NotificationStateStore(
            state_path=state_dir / "cio_notification_state.jsonl",
            audit_path=state_dir / "cio_notification_audit.jsonl",
            metrics_path=state_dir / "cio_notification_metrics.jsonl",
        )
        with store.locked():
            # Serialize the decide+record read-modify-write so two concurrent
            # scanner runs cannot both observe "never told" and double-send.
            for cand in candidates:
                nd = decide_notification(cand, store=store)
                key = str(cand.get("decision_id") or "")
                nd_map[key] = nd
                if persist:
                    store.record(nd)

    selected = select_publications(candidates, max_publish=max_publish)
    results = []
    for dec in selected:
        nd = nd_map.get(str(dec.get("decision_id") or ""))
        is_immediate = nd is not None and nd.get("notification_class") == DELIVERY_IMMEDIATE
        effective_dry = dry_run if nd is None else (dry_run or not is_immediate)
        body = render_cio_card(dec, nd) if (is_immediate and nd is not None) else None
        holdings_row = next((r for r in curr_rows if r.get("symbol") == dec.get("symbol")), None)
        results.append(publish_material_decision(
            dec,
            capital_plan=plan if isinstance(plan, dict) else None,
            holdings_row=holdings_row,
            dry_run=effective_dry,
            event_type=str(dec.get("action") or "DECISION"),
            body=body,
            notification=nd,
        ))

    if persist and holdings.get("ok") is not False:
        save_holdings_snapshot(holdings, events=events)
        save_office_state({
            "captured_at": _now(),
            "authority": AUTHORITY,
            "cash_digest": (plan or {}).get("digest"),
            "cash_posture_status": (plan or {}).get("cash_posture_status"),
            "freshness_counts": ((plan.get("freshness_materiality_gate") or {}).get("counts")
                                 if isinstance(plan.get("freshness_materiality_gate"), dict) else {}),
            "reentry_call": reclass.get("call"),
            "reentry_ready": reclass.get("ready"),
            "published_ids": [d.get("decision_id") for d in selected],
        })

    notification_counts: dict[str, int] = {}
    suppressed_by_reason: dict[str, int] = {}
    immediate_ids: list[str] = []
    if nd_map:
        for nd in nd_map.values():
            cls = str(nd.get("notification_class") or "UNKNOWN")
            notification_counts[cls] = notification_counts.get(cls, 0) + 1
            if cls == "IMMEDIATE":
                immediate_ids.append(str(nd.get("decision_id") or ""))
            reason = nd.get("suppressed_reason")
            if reason:
                suppressed_by_reason[reason] = suppressed_by_reason.get(reason, 0) + 1
    if store is not None and persist:
        try:
            store.record_metrics({
                "scanner_wakes": 1,
                "candidate_decisions": len(candidates),
                "immediate_notifications": notification_counts.get("IMMEDIATE", 0),
                "digest_notifications": notification_counts.get("DIGEST", 0),
                "command_center_only": notification_counts.get("COMMAND_CENTER_ONLY", 0),
                "suppressed_unchanged": notification_counts.get("SUPPRESSED", 0),
                "suppressed_post_reject": sum(
                    v for k, v in suppressed_by_reason.items() if "reject" in k
                ),
            })
        except Exception:
            pass

    receipt = {
        "ok": True,
        "dry_run": dry_run,
        "delivery_mode": mode,
        "material_financial_notify_canary": canary,
        "financial_lane": "CANARY" if (canary and mode == "CIO_ONLY_LIVE" and not dry_run) else "OFF_BY_POLICY",
        "authority": AUTHORITY,
        "at": _now(),
        "baseline_captured": baseline,
        "holdings_events": events,
        "candidates": len(candidates),
        "published": len(results),
        "results": results,
        "cash": cash_posture(plan) if plan else {},
        "reentry": reclass,
        "due_defers": len(due),
        "schg": next((r for r in curr_rows if r.get("symbol") == "SCHG"), None),
        "notification_gate": notification_gate,
        "notification_counts": notification_counts,
        "suppressed_by_reason": suppressed_by_reason,
        "immediate_decision_ids": immediate_ids,
        "note": (
            "Baseline captured — no POSITION_OPENED invented from first snapshot."
            if baseline else
            "Diffed against persisted verified holdings snapshot."
        ),
    }

    # Additive flag-gated observability (AIF). OFF by default => no key added,
    # so the receipt is byte-for-byte the pre-AIF shape.
    aif = _instrument_scan(selected, at=receipt["at"])
    if aif:
        receipt["aif_observability"] = aif
    if persist:
        RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT_PATH.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
        receipt["receipt_path"] = str(RECEIPT_PATH)
    return receipt
