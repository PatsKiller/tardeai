"""Expire revisit-overdue duplicate S1 plans. Keep the newest per symbol.

Operator judgment, 2026-08-29: *"Do not mass-cancel. Dry: keep newest open per
symbol; expire revisit-overdue dups only."*

109 duplicate open S1 plans accumulated daily between 2026-08-11 and 08-28 on
six held names, before #609's "skip duplicate open S1" guard shipped. The guard
holds — 9 S1 plans created since, none sharing a symbol — so this is backlog,
not a live leak, and it is cleared under two deliberate constraints:

* **Newest per symbol is always kept.** The name keeps its lifecycle plan; only
  the redundant copies go.
* **Only revisit-overdue copies are expired.** A duplicate whose `revisit_at`
  is still in the future is left alone — it is redundant but not yet stale, and
  expiring it would be a judgment about the plan rather than about the backlog.

Cancel, never delete. Dry by default. `notify: false`.

READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
S1 = "S1_POSITION_LIFECYCLE"
ACTOR = "cio_duplicate_s1_hygiene"
REASON = "duplicate_s1_revisit_overdue"


def _parse(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def select_duplicate_s1(
    store: Any,
    *,
    now: Optional[datetime] = None,
    limit: int = 0,
) -> dict[str, Any]:
    """Revisit-overdue duplicates, newest-per-symbol always retained."""
    now = now or datetime.now(timezone.utc)
    try:
        rows = store.list_open_plans(situation_type=S1, limit=100000) or []
    except TypeError:
        rows = [p for p in (store.list_open_plans(limit=100000) or [])
                if p.get("situation_type") == S1]

    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for plan in rows:
        if not isinstance(plan, dict):
            continue
        for raw in (plan.get("symbols") or []):
            sym = str(raw).strip().upper()
            if sym:
                by_symbol.setdefault(sym, []).append(plan)

    expire: list[dict[str, Any]] = []
    kept: dict[str, str] = {}
    retained_not_overdue: list[dict[str, Any]] = []

    for sym in sorted(by_symbol):
        plans = sorted(
            by_symbol[sym],
            key=lambda p: str(p.get("created_ts") or ""),
            reverse=True,
        )
        kept[sym] = str(plans[0].get("plan_id") or "")
        for plan in plans[1:]:
            revisit = _parse(plan.get("revisit_at"))
            row = {
                "plan_id": plan.get("plan_id"),
                "symbol": sym,
                "status": plan.get("status"),
                "created_ts": plan.get("created_ts"),
                "revisit_at": plan.get("revisit_at"),
                "class": "D",
            }
            if revisit is not None and revisit < now:
                expire.append(row)
            else:
                retained_not_overdue.append(row)

    if limit:
        expire = expire[: int(limit)]

    by_sym_count: dict[str, int] = {}
    for row in expire:
        by_sym_count[row["symbol"]] = by_sym_count.get(row["symbol"], 0) + 1

    return {
        "schema": "DuplicateS1Hygiene@v1",
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "symbols_seen": len(by_symbol),
        "kept_newest_per_symbol": kept,
        "would_expire": len(expire),
        "by_symbol": by_sym_count,
        "expire": expire,
        "retained_not_overdue": retained_not_overdue,
        "retained_not_overdue_n": len(retained_not_overdue),
        "note": (
            "Newest per symbol is always kept. A duplicate whose revisit_at is "
            "still in the future is redundant but not stale, and is left alone."
        ),
    }


def expire_duplicate_s1(
    store: Any,
    *,
    now: Optional[datetime] = None,
    apply: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    dry = select_duplicate_s1(store, now=now, limit=limit)
    expired: list[str] = []
    if apply:
        for row in dry["expire"]:
            pid = str(row.get("plan_id") or "")
            if not pid:
                continue
            store.update_plan(
                pid,
                status="cancelled",
                status_reason=REASON,
                actor_id=ACTOR,
            )
            expired.append(pid)
    return {
        **dry,
        "apply": bool(apply),
        "expired": len(expired),
        "expired_plan_ids": expired,
        "notify": False,
        "deletes_history": False,
    }
