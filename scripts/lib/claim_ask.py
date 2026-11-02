"""Ask the real holder of a claimed path, instead of guessing which session to message.

2026-11-01: a session asked the wrong session to release files and wasted turns. The claim board
already knows who holds a path (`agent_claim.py check <path>`); this turns that into the one
actionable answer — the holder's session name and the message to send — and points a stale claim
at `takeover`, which is the only route that never starts over (AGENTS.md §28.3a).

AUTHORITY: READ_ONLY_ADVISORY. It reads the board and prints; it sends nothing itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

SCHEMA = "AgentClaimAsk@v1"


def _age_hours(now_iso: str, then_iso: Optional[str]) -> Optional[float]:
    if not then_iso:
        return None
    try:
        a = datetime.strptime(now_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        b = datetime.strptime(then_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return round((a - b).total_seconds() / 3600.0, 2)


def plan_ask(
    rows: Iterable[Mapping[str, Any]],
    *,
    now_iso: str,
    stale_hours: float = 2.0,
    message: Optional[str] = None,
    paths: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Shape the holder list: who to message, and whether to take the claim over instead."""
    holders: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows or []:
        if str(row.get("source") or "") != "claim":
            continue  # a draft-PR conflict is not a claim board holder
        claim_id = str(row.get("claim_id") or "")
        if not claim_id or claim_id in seen:
            continue
        seen.add(claim_id)
        age = _age_hours(now_iso, row.get("heartbeat_at"))
        stale = age is not None and age >= stale_hours
        holders.append(
            {
                "session": row.get("session"),
                "agent": row.get("agent"),
                "claim_id": claim_id,
                "branch": row.get("branch"),
                "task": row.get("task"),
                "heartbeat_age_hours": age,
                "stale": stale,
                "held": sorted({str(o.get("held")) for o in row.get("overlaps") or [] if o.get("held")}),
                # The only correct next step for each case:
                "next": "agent_claim.py takeover" if stale else "SendMessage to this session",
            }
        )
    return {
        "schema": SCHEMA,
        "at": now_iso,
        "paths": list(paths or []),
        "conflict": bool(holders),
        "holders": holders,
        "message": message,
    }


def render(out: Mapping[str, Any]) -> str:
    """Plain lines a person or an agent can act on without reading the JSON."""
    holders = out.get("holders") or []
    if not holders:
        return "no claim holds these paths — go ahead and claim them"
    lines = []
    for h in holders:
        who = h.get("session") or h.get("agent") or "(unnamed session)"
        age = h.get("heartbeat_age_hours")
        stamp = f", last heartbeat {age}h ago" if age is not None else ""
        lines.append(f"held by {who} — claim {h['claim_id']}, branch {h.get('branch')}{stamp}")
        if h.get("held"):
            lines.append(f"  held paths: {', '.join(h['held'])}")
        if h.get("stale"):
            lines.append("  stale: take it over with `scripts/agent_claim.py takeover " + h["claim_id"] + "`")
        elif h.get("session"):
            lines.append(f"  message it: SendMessage to {h['session']}")
    if out.get("message"):
        lines.append(f"suggested message: {out['message']}")
    return "\n".join(lines)
