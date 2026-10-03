"""Which open CIO plans have gone stale enough to expire (operator-approved 2026-10-03).

Nothing ever closed a draft or proposed plan, so 1,010 sat open with 973 past
their own revisit date and the CIO Desk "Decisions" card stayed DEGRADED.

Rule (deterministic, no LLM): a draft/proposed plan expires when its
``revisit_at`` passed at least ``grace_days`` ago AND it has not been updated in
``grace_days``. Accepted plans are never touched, and a plan whose dates cannot
be read is left alone. Expiry is an append-only status event with the reason.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from scripts.lib.cio_plans import EXPIRABLE

DEFAULT_GRACE_DAYS = 14
SCHEMA = "CIOPlanExpiry@v1"


def _ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            t = datetime.fromtimestamp(float(value), timezone.utc)
        else:
            t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def expiry_reason(plan: dict[str, Any], *, now: datetime, grace_days: int = DEFAULT_GRACE_DAYS) -> str | None:
    """The reason this plan expires now, or None when it must stay open."""
    if str(plan.get("status") or "") not in EXPIRABLE:
        return None
    revisit = _ts(plan.get("revisit_at"))
    touched = _ts(plan.get("updated_ts")) or _ts(plan.get("created_ts"))
    if revisit is None or touched is None:
        return None
    overdue = (now - revisit).days
    idle = (now - touched).days
    if overdue < grace_days or idle < grace_days:
        return None
    return (f"revisit_at {revisit.date().isoformat()} passed by {overdue}d with no update in "
            f"{idle}d (grace {grace_days}d)")


def expiry_candidates(
    plans: Iterable[dict[str, Any]], *, now: datetime | None = None, grace_days: int = DEFAULT_GRACE_DAYS,
) -> list[tuple[dict[str, Any], str]]:
    now = now or datetime.now(timezone.utc)
    out: list[tuple[dict[str, Any], str]] = []
    for plan in plans:
        if isinstance(plan, dict):
            reason = expiry_reason(plan, now=now, grace_days=grace_days)
            if reason:
                out.append((plan, reason))
    return out
