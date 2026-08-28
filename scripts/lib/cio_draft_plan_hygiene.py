"""Expire stale empty draft plans. Do not delete JSONL history.

Eligible: status=draft, no hermes_result_id, revisit_at in the past,
not S5/S6. Dry-run by default. --apply writes PLAN_STATUS_CHANGED
to cancelled only.

READ_ONLY_ADVISORY. No notify.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from scripts.lib.cio_plans import CIOPlanStore

AUTHORITY = "READ_ONLY_ADVISORY"
PROTECTED_SITUATIONS = frozenset({
    "S5_CASH_DEPLOYMENT",
    "S6_CONCENTRATION_OR_DISPOSITION",
})
HYGIENE_REASON = "draft_hygiene_revisit_overdue"


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def is_stale_empty_draft(plan: dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    if str(plan.get("status") or "") != "draft":
        return False
    if plan.get("hermes_result_id"):
        return False
    if str(plan.get("situation_type") or "") in PROTECTED_SITUATIONS:
        return False
    if plan.get("material") is True and str(plan.get("situation_type") or "").startswith("S5"):
        return False
    if plan.get("material") is True and str(plan.get("situation_type") or "").startswith("S6"):
        return False
    revisit = _parse_ts(plan.get("revisit_at"))
    if revisit is None:
        return False
    now = now or datetime.now(timezone.utc)
    return revisit < now


def select_stale_empty_drafts(
    store: CIOPlanStore,
    *,
    now: Optional[datetime] = None,
    limit: int = 0,
) -> list[dict[str, Any]]:
    rows = []
    for plan in store._plans.values():
        if not isinstance(plan, dict):
            continue
        if is_stale_empty_draft(plan, now=now):
            rows.append(dict(plan))
    rows.sort(key=lambda p: str(p.get("revisit_at") or ""))
    if limit:
        rows = rows[:limit]
    return rows


def expire_stale_empty_drafts(
    store: CIOPlanStore,
    *,
    apply: bool = False,
    now: Optional[datetime] = None,
    limit: int = 0,
) -> dict[str, Any]:
    candidates = select_stale_empty_drafts(store, now=now, limit=limit)
    expired: list[str] = []
    if apply:
        for plan in candidates:
            pid = str(plan.get("plan_id") or "")
            if not pid:
                continue
            store.update_plan(
                pid,
                status="cancelled",
                status_reason=HYGIENE_REASON,
                actor_id="cio_draft_plan_hygiene",
            )
            expired.append(pid)
    return {
        "schema": "DraftPlanHygiene@v1",
        "authority": AUTHORITY,
        "apply": apply,
        "would_expire": len(candidates),
        "expired": len(expired),
        "samples": [
            {
                "plan_id": p.get("plan_id"),
                "situation_type": p.get("situation_type"),
                "symbols": p.get("symbols"),
                "revisit_at": p.get("revisit_at"),
            }
            for p in candidates[:8]
        ],
        "financial_action": False,
        "notify": False,
    }
