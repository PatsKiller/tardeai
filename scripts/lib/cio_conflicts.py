"""CIO-owned conflict projections for review, brief, Ask and promotion consumers.

The schemas are produced by the one nested conflict ledger writer. These explicit
references bring them into the native CIO census rather than hiding a nested store.
"""
from datetime import datetime, timezone

from scripts.lib.conflicts.adapters import timestamp
from scripts.lib.conflicts.cio import context_for, digest
from scripts.lib.conflicts.ledger import list_records

EVENT_SCHEMA = "ConflictEvent@v1"
RECORD_SCHEMA = "ConflictRecord@v1"
DECISION_SCHEMA = "ConflictDecision@v1"


def conflicts_for(root, security_guid):
    """Shared records, never per-consumer classification or source selection."""
    return context_for(root, security_guid)


def brief_context(root):
    return digest(root)


def conviction_gate(root, security_guid):
    context = context_for(root, security_guid)
    return {"actionable_promotion_allowed": not context["blocks_promotion"],
            "reason": (context.get("gap") or {}).get("reason") or "open conflict requires a current owner decision or source repair"
            if context["blocks_promotion"] else None,
            "conflicts": context["open_conflicts"]}


def ask_context_rows(root, security_guid, *, now=None):
    """Read-only current rows for Ask memory; never append a poll contribution.

    Canonical CIO stance remains the existing GUID-bound CIO projection. A
    recorded conflict decision is labelled separately from that stance.

    Each row also carries ``opened_at`` and ``age_hours``: the ledger keeps the FIRST open time across
    re-reconciles, so it is the clock a reader needs to tell an item that has waited an hour from one that has waited
    nine days. ``age_hours`` is None when the open time is unreadable — never a fabricated zero.
    """
    now = now or datetime.now(timezone.utc)
    context = context_for(root, security_guid)
    if context.get("gap"):
        return [{"at": None, "kind": "conflict.current", "summary": "Current conflict evaluation unavailable: "
                 + context["gap"]["reason"], "ref": f"conflicts:{security_guid}:unavailable",
                 "source": "conflict_events.jsonl", "current_conflicts": [], "gap": context["gap"]}]
    records = context["open_conflicts"]
    if not records:
        return []
    rows = []
    for record in records:
        row = {k: record.get(k) for k in ("key", "state", "kind", "summary", "sides", "clears_when", "owner",
                                          "next_run", "decision", "updated_at", "revision")}
        opened = timestamp(record.get("opened_at"))
        seconds = (now - opened).total_seconds() if opened else None
        row["opened_at"] = opened.isoformat().replace("+00:00", "Z") if opened else None
        row["age_hours"] = round(seconds / 3600, 1) if seconds is not None and seconds >= 0 else None
        rows.append(row)
    summary = "; ".join(f"{r['state']}: {r['summary']} — clears when {r['clears_when']}" for r in rows)
    # Same honesty rule as opened_at: an unreadable clock is absent, never a fabricated value (and never a
    # TypeError). Only rows whose updated_at / revision were actually recorded can set the summary clock.
    updated = [r["updated_at"] for r in rows if r.get("updated_at") is not None]
    revisions = [r["revision"] for r in rows if isinstance(r.get("revision"), (int, float))]
    return [{"at": max(updated) if updated else None, "kind": "conflict.current", "summary": summary,
             "ref": f"conflicts:{security_guid}:" + (str(max(revisions)) if revisions else "unknown"),
             "source": "conflict_events.jsonl", "current_conflicts": rows, "gap": None}]
