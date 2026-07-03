"""Human approval workflow — approve, reject, rollback."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .store import (
    append_audit,
    get_active_value,
    last_audit_event,
    load_active_thresholds,
    load_proposals,
    load_threshold_config,
    save_active_thresholds,
    save_proposals,
    static_defaults,
)

_SHORT_LABELS: dict[str, str] = {
    "efficiency.tighten_threshold": "Efficiency",
    "stop_quality.divergence_delta_pp": "Stop Quality Divergence",
}


def _learning_readiness(cfg: dict[str, Any]) -> dict[str, Any]:
    """Bus history depth vs min_history_days — drives UI collecting-data state."""
    learning = cfg.get("learning") or {}
    min_hist = int(learning.get("min_history_days", 14))
    window = int(learning.get("analysis_window_days", 30))
    history_days = 0
    try:
        from lib.hermes_outcome_bus.bus import load_outcome_bus_trend

        trend = load_outcome_bus_trend(days=window)
        history_days = int(trend.get("count") or len(trend.get("series") or []))
    except Exception:
        pass
    learning_ready = history_days >= min_hist
    return {
        "history_days": history_days,
        "min_history_days": min_hist,
        "learning_ready": learning_ready,
        "learning_status": "active" if learning_ready else "collecting_data",
    }


def _format_proposal_delta(p: dict[str, Any]) -> str:
    tid = str(p.get("threshold_id") or "")
    short = _SHORT_LABELS.get(tid) or str(p.get("label") or tid).split("(")[0].strip()
    cur = float(p.get("current_value") or 0)
    prop = float(p.get("proposed_value") or 0)
    delta = prop - cur
    sign = "+" if delta > 0 else ""
    if "divergence" in tid or tid.startswith("stop_quality"):
        return f"{short} {sign}{delta * 100:.0f}pp"
    return f"{short} {sign}{delta:.2f}"


def _pending_summary_text(pending: list[dict[str, Any]]) -> str:
    if not pending:
        return "No pending adjustments"
    parts = [_format_proposal_delta(p) for p in pending]
    n = len(pending)
    head = f"{n} proposal{'s' if n != 1 else ''} pending review"
    return f"{head} ({', '.join(parts)})"


def threshold_status() -> dict[str, Any]:
    """Current active vs static defaults + pending proposals."""
    cfg = load_threshold_config()
    defaults = static_defaults(cfg)
    active = load_active_thresholds()
    proposals = load_proposals()
    learning = cfg.get("learning") or {}

    pending = list(proposals.get("pending") or [])
    pending_by_tid = {p["threshold_id"]: p for p in pending if p.get("threshold_id")}
    last_proposed = last_audit_event("proposed")
    last_change = (active.get("history") or [])[-1] if active.get("history") else None

    rows = []
    for tid, spec in defaults.items():
        learned = (active.get("thresholds") or {}).get(tid)
        current = get_active_value(tid, cfg)
        pending_p = pending_by_tid.get(tid)
        if pending_p:
            status = "pending_review"
        elif learned is not None:
            status = "learned"
        else:
            status = "static"
        rows.append({
            "threshold_id": tid,
            "label": spec.get("label", tid),
            "static_default": spec["value"],
            "active_value": current,
            "proposed_value": (pending_p or {}).get("proposed_value"),
            "status": status,
            "is_learned": learned is not None,
            "approved_at": (learned or {}).get("approved_at"),
            "approved_by": (learned or {}).get("approved_by"),
            "safe_band": spec.get("safe_band"),
            "path": spec.get("path"),
            "pending_proposal_id": (pending_p or {}).get("id"),
        })

    eval_summary = {}
    try:
        from .evaluation_engine import evaluation_status
        eval_summary = evaluation_status().get("summary") or {}
    except Exception:
        pass

    readiness = _learning_readiness(cfg)
    pending_summary = _pending_summary_text(pending)
    first_pending_id = pending[0]["id"] if pending else None

    return {
        "ok": True,
        "scoring_version": "scoring-v2",
        "learning_enabled": learning.get("enabled", True),
        "review_mode": learning.get("review_mode", True),
        **readiness,
        "thresholds": rows,
        "pending_proposals": pending,
        "pending_count": len(pending),
        "pending_summary": pending_summary,
        "decided_proposals": (proposals.get("decided") or [])[-5:],
        "history": (active.get("history") or [])[-10:],
        "active_source": active.get("source", "static"),
        "updated_at": active.get("updated_at"),
        "proposals_updated_at": proposals.get("updated_at"),
        "last_evaluated_at": (last_proposed or {}).get("at"),
        "last_changed_at": (last_change or {}).get("at"),
        "evaluation_summary": eval_summary,
        "cli_commands": {
            "status": ".venv/bin/python scripts/hermes_threshold_learner.py --status",
            "learn": ".venv/bin/python scripts/hermes_threshold_learner.py --learn",
            "learn_apply": ".venv/bin/python scripts/hermes_threshold_learner.py --learn --apply",
            "approve": (
                f".venv/bin/python scripts/hermes_threshold_learner.py --approve {first_pending_id}"
                if first_pending_id
                else ".venv/bin/python scripts/hermes_threshold_learner.py --approve <proposal_id>"
            ),
            "evaluate": ".venv/bin/python scripts/hermes_threshold_learner.py --evaluate",
        },
    }


def _proposal_lookup(proposal_id: str) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]], str | None]:
    """Return (match, proposals_store, pending_list, error_reason)."""
    proposals = load_proposals()
    pending = list(proposals.get("pending") or [])
    match = next((p for p in pending if p.get("id") == proposal_id), None)
    if match:
        if str(match.get("status") or "pending") != "pending":
            return None, proposals, pending, "invalid_proposal_state"
        return match, proposals, pending, None

    for decided in proposals.get("decided") or []:
        if decided.get("id") == proposal_id:
            return None, proposals, pending, "already_processed"
    return None, proposals, pending, "proposal_not_found"


def _should_apply_on_approve(cfg: dict[str, Any], force_apply: bool) -> bool:
    """Manual approve applies by default; review_mode blocks unless force_apply."""
    learning = cfg.get("learning") or {}
    if not learning.get("enabled", True):
        return False
    if force_apply:
        return True
    return not bool(learning.get("review_mode", True))


def approve_proposal(
    proposal_id: str,
    approved_by: str = "operator",
    override_value: float | None = None,
    notes: str | None = None,
    reason: str | None = None,
    force_apply: bool = True,
) -> dict[str, Any]:
    match, proposals, pending, err = _proposal_lookup(proposal_id)
    if err or not match:
        return {"ok": False, "reason": err or "proposal_not_found", "proposal_id": proposal_id}

    cfg = load_threshold_config()
    spec = static_defaults(cfg).get(match["threshold_id"])
    if not spec:
        return {"ok": False, "reason": "unknown_threshold_id"}

    band = spec.get("safe_band") or {}
    val = float(override_value if override_value is not None else match["proposed_value"])
    max_step = float(spec.get("max_step", 0.03))
    current = float(match.get("current_value") or get_active_value(match["threshold_id"], cfg) or val)
    if abs(val - current) > max_step + 1e-6:
        return {"ok": False, "reason": "exceeds_max_step", "value": val, "current": current, "max_step": max_step}
    lo, hi = float(band.get("min", val)), float(band.get("max", val))
    if not (lo <= val <= hi):
        return {"ok": False, "reason": "outside_safe_band", "value": val, "band": band}
    if override_value is not None:
        match = {**match, "proposed_value": val, "modified_by": approved_by, "modify_note": "operator_override"}

    prev = get_active_value(match["threshold_id"], cfg)
    now = datetime.now(timezone.utc).isoformat()
    apply_active = _should_apply_on_approve(cfg, force_apply)

    if apply_active:
        active = load_active_thresholds()
        thresholds = dict(active.get("thresholds") or {})
        history = list(active.get("history") or [])
        thresholds[match["threshold_id"]] = {
            "value": val,
            "approved_at": now,
            "approved_by": approved_by,
            "proposal_id": proposal_id,
            "previous_value": prev,
            "reasoning": match.get("reasoning"),
            "operator_notes": notes,
            "operator_reason": reason,
        }
        history.append({
            "at": now,
            "threshold_id": match["threshold_id"],
            "from": prev,
            "to": val,
            "action": "approved",
            "proposal_id": proposal_id,
            "approved_by": approved_by,
            "reason": reason or notes or match.get("reasoning"),
        })
        save_active_thresholds({
            "version": "thresholds-v1",
            "source": "learned",
            "thresholds": thresholds,
            "history": history[-50:],
        })

    match = {
        **match,
        "status": "approved",
        "decided_at": now,
        "approved_by": approved_by,
        "applied": apply_active,
        "operator_notes": notes,
        "operator_reason": reason,
    }
    pending = [p for p in pending if p.get("id") != proposal_id]
    decided = list(proposals.get("decided") or [])
    decided.append(match)
    save_proposals({**proposals, "pending": pending, "decided": decided[-30:]})

    append_audit({
        "action": "approved" if apply_active else "approved_review_only",
        "proposal_id": proposal_id,
        "threshold_id": match["threshold_id"],
        "proposal": {
            "label": match.get("label"),
            "current_value": current,
            "proposed_value": val,
            "direction": match.get("direction"),
            "confidence": (match.get("evidence") or {}).get("confidence"),
        },
        "from": prev,
        "to": val if apply_active else prev,
        "applied": apply_active,
        "review_mode": bool((cfg.get("learning") or {}).get("review_mode", True)),
        "force_apply": force_apply,
        "approved_by": approved_by,
        "notes": notes,
        "reason": reason,
        "governor_merge_ready": apply_active,
    })

    return {
        "ok": True,
        "proposal_id": proposal_id,
        "threshold_id": match["threshold_id"],
        "from": prev,
        "to": val if apply_active else prev,
        "approved_by": approved_by,
        "applied": apply_active,
        "review_mode_blocked": not apply_active,
        "governor_merge_ready": apply_active,
    }


def reject_proposal(
    proposal_id: str,
    reason: str = "operator_rejected",
    notes: str | None = None,
    rejected_by: str = "operator",
) -> dict[str, Any]:
    match, proposals, pending, err = _proposal_lookup(proposal_id)
    if err or not match:
        return {"ok": False, "reason": err or "proposal_not_found", "proposal_id": proposal_id}

    now = datetime.now(timezone.utc).isoformat()
    full_reason = reason
    if notes and notes not in reason:
        full_reason = f"{reason}: {notes}" if reason else notes

    match = {
        **match,
        "status": "rejected",
        "decided_at": now,
        "reject_reason": full_reason,
        "rejected_by": rejected_by,
        "operator_notes": notes,
    }
    pending = [p for p in pending if p.get("id") != proposal_id]
    decided = list(proposals.get("decided") or [])
    decided.append(match)
    save_proposals({**proposals, "pending": pending, "decided": decided[-30:]})

    append_audit({
        "action": "rejected",
        "proposal_id": proposal_id,
        "threshold_id": match.get("threshold_id"),
        "proposal": {
            "label": match.get("label"),
            "current_value": match.get("current_value"),
            "proposed_value": match.get("proposed_value"),
            "direction": match.get("direction"),
        },
        "reason": full_reason,
        "notes": notes,
        "rejected_by": rejected_by,
        "applied": False,
    })
    return {
        "ok": True,
        "proposal_id": proposal_id,
        "status": "rejected",
        "reason": full_reason,
        "rejected_by": rejected_by,
    }


def rollback_thresholds(approved_by: str = "operator") -> dict[str, Any]:
    """Revert all learned thresholds to static yaml defaults."""
    cfg = load_threshold_config()
    defaults = static_defaults(cfg)
    active = load_active_thresholds()
    history = list(active.get("history") or [])
    now = datetime.now(timezone.utc).isoformat()
    rolled: list[dict[str, Any]] = []

    for tid, spec in defaults.items():
        prev = get_active_value(tid, cfg)
        static_val = float(spec["value"])
        if prev is not None and abs(prev - static_val) < 1e-6:
            continue
        history.append({
            "at": now,
            "threshold_id": tid,
            "from": prev,
            "to": static_val,
            "action": "rollback",
            "approved_by": approved_by,
            "reason": "rollback_to_static_defaults",
        })
        rolled.append({"threshold_id": tid, "from": prev, "to": static_val})

    save_active_thresholds({
        "version": "thresholds-v1",
        "source": "static",
        "thresholds": {},
        "history": history[-50:],
        "rolled_back_at": now,
        "rolled_back_by": approved_by,
    })

    append_audit({"action": "rollback", "rolled": rolled, "by": approved_by})
    return {"ok": True, "rolled": rolled, "count": len(rolled)}