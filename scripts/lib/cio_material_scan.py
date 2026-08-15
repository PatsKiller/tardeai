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

from scripts.lib.cio_alex_telegram import due_defers
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
        },
    )


def _reentry_decision(reclass: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    ready = reclass.get("ready") or []
    near = reclass.get("near") or []
    act_now = 0
    gate = plan.get("freshness_materiality_gate") if isinstance(plan.get("freshness_materiality_gate"), dict) else {}
    try:
        act_now = int(gate.get("act_now_count") or 0)
    except (TypeError, ValueError):
        act_now = 0
    # Desk "READY TO REVIEW" is not ACT_NOW. Without fresh marks, WAIT.
    if ready and act_now > 0:
        action = "RE_ENTER"
        why = (
            f"Re-entry desk has READY names: {', '.join(ready[:8])}. "
            f"ACT_NOW={act_now}. Advisory only."
        )
        change = "READY names leave the zone or wash/freshness blocks them."
        delta = float((cash_posture(plan).get("reentry_usd") or 0))
    elif ready or near:
        action = "WAIT"
        why = (
            f"Re-entry WAIT. Desk READY={', '.join(ready[:6]) or 'none'} "
            f"NEAR={', '.join(near[:6]) or 'none'} but ACT_NOW={act_now}. "
            "Do not chase stale marks."
        )
        change = "READY names survive freshness and a capital-plan use is ACT_NOW."
        delta = 0.0
    else:
        action = "WAIT"
        why = (
            f"Re-entry WAIT. READY=0 NEAR={len(near)} WAIT={len(reclass.get('wait') or [])} "
            f"of {reclass.get('n') or 0} desk rows. No re-entry dollars in the capital plan."
        )
        change = "Desk prints READY with fresh marks and a capital-plan use."
        delta = 0.0
    return _decision(
        decision_id=f"dec_reentry_{_digest({'action': action, 'ready': ready[:12], 'near': near[:12], 'act_now': act_now})}",
        symbol="REENTRY",
        action=action,
        why=why,
        counter="A subset of WAIT names may be near-trigger on a different desk definition.",
        change=change,
        delta=delta,
        extra={"reentry": reclass},
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
            "decision_input_digest": row.get("decision_input_digest") or "",
            "weight_pct": row.get("current_weight_pct") or row.get("weight_pct"),
            "current_value_usd": row.get("current_value_usd"),
            "act_now": row.get("act_now"),
            "actionable": row.get("actionable"),
            "action_label": row.get("action_label"),
            "account": row.get("account"),
        }
        # Freshness is STALE → do not pretend ACT NOW.
        label = str(row.get("action_label") or "")
        if label and "STALE" in label.upper():
            why = f"{why} Freshness={label}; not ACT NOW."
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
        extra={"freshness_counts": counts, "prior": prev_counts},
    )


def select_publications(
    candidates: list[dict[str, Any]],
    *,
    max_publish: int = 3,
) -> list[dict[str, Any]]:
    """Prefer book events, then cash, then one standing TRIM. Avoid flood."""
    opened = [c for c in candidates if str(c.get("extra_event") or c.get("event") or "") == "POSITION_OPENED"
              or str(c.get("decision_id") or "").startswith("dec_open_")]
    xfer = [c for c in candidates if str(c.get("decision_id") or "").startswith("dec_xfer_")]
    cash = [c for c in candidates if c.get("symbol") == "CASH"]
    reentry = [c for c in candidates if c.get("symbol") == "REENTRY"]
    trims = [c for c in candidates if str(c.get("action") or "").upper() == "TRIM"]
    other = [c for c in candidates if c not in opened + xfer + cash + reentry + trims]
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


def scan_office(
    *,
    dry_run: bool = True,
    office: Optional[dict[str, Any]] = None,
    persist: bool = True,
    max_publish: int = 3,
) -> dict[str, Any]:
    mode = cio_delivery_mode()
    if not dry_run and mode != "CIO_ONLY_LIVE":
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

    selected = select_publications(candidates, max_publish=max_publish)
    results = []
    for dec in selected:
        holdings_row = next((r for r in curr_rows if r.get("symbol") == dec.get("symbol")), None)
        results.append(publish_material_decision(
            dec,
            capital_plan=plan if isinstance(plan, dict) else None,
            holdings_row=holdings_row,
            dry_run=dry_run,
            event_type=str(dec.get("action") or "DECISION"),
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

    receipt = {
        "ok": True,
        "dry_run": dry_run,
        "delivery_mode": mode,
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
        "note": (
            "Baseline captured — no POSITION_OPENED invented from first snapshot."
            if baseline else
            "Diffed against persisted verified holdings snapshot."
        ),
    }
    if persist:
        RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT_PATH.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
        receipt["receipt_path"] = str(RECEIPT_PATH)
    return receipt
