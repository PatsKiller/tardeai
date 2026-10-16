"""effect_ownership_watch.py — P1 rows for cron copies that FAILED CLOSED because ownership was unknown (2026-10-16).

scripts/effect_claim_cron.sh skips a handed-over lane whose ownership it cannot establish (ledger unreachable, handover
manifest unreadable, or manifest and ledger disagree) and appends one EffectOwnershipIncident@v1 row to
``<state>/data/runtime/effect_ownership_incidents.jsonl`` (written by bash, so a broken interpreter still records it).
This module turns the rows of the last ``TRADEAI_EFFECT_OWNERSHIP_WINDOW_H`` hours (default 6) into fan-in-shaped P1
findings, one per lane (source ``effect_ownership``, item ``<lane>:OWNERSHIP_UNKNOWN``). The finding clears itself once
no row for the lane is inside the window.

Two readers, same source/item keys (so one incident, never two): scripts/incident_notifier.py (host cron: the P1 does
not depend on the ledger or n8n, which are exactly what may be down) and scripts/n8n_incident_fanin.py (the SIEM row).

AUTHORITY: READ_ONLY_ADVISORY. Reads one jsonl file; writes nothing.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

NO_CONSUMER_REASON = "Library of scripts/incident_notifier.py and scripts/n8n_incident_fanin.py."
SOURCE = "effect_ownership"
INCIDENTS_REL = "data/runtime/effect_ownership_incidents.jsonl"
DEFAULT_WINDOW_H = 6.0
MAX_BYTES = 1_000_000


def _ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def findings(root: Path, now: datetime, env: Optional[dict] = None) -> tuple[list[dict[str, Any]], str]:
    """(P1 findings, note). A missing file is a note, never a finding."""
    env = os.environ if env is None else env
    try:
        window = timedelta(hours=float(env.get("TRADEAI_EFFECT_OWNERSHIP_WINDOW_H") or DEFAULT_WINDOW_H))
    except ValueError:
        window = timedelta(hours=DEFAULT_WINDOW_H)
    path = Path(root) / INCIDENTS_REL
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - MAX_BYTES))
            lines = fh.read().decode("utf-8", "replace").splitlines()[1 if size > MAX_BYTES else 0:]
    except FileNotFoundError:
        return [], "effect_ownership:absent"
    except OSError as exc:
        return [], f"effect_ownership:unreadable:{type(exc).__name__}"
    by_lane: dict[str, dict[str, Any]] = {}
    for ln in lines:
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        at = _ts(r.get("ts"))
        if at is None or at > now + timedelta(minutes=5) or now - at > window:
            continue
        lane = str(r.get("lane") or "unknown")
        cur = by_lane.get(lane)
        n = (cur or {}).get("count", 0) + 1
        if cur is None or at >= cur["at"]:
            by_lane[lane] = {"at": at, "count": n, "row": r}
        else:
            cur["count"] = n
    out = []
    for lane, d in sorted(by_lane.items()):
        r = d["row"]
        out.append({
            "source": SOURCE,
            "item": f"{lane}:OWNERSHIP_UNKNOWN",
            "severity": "P1",
            "lane": lane,
            "detail": (f"cron copy of {lane} (process {r.get('process')}) FAILED CLOSED x{d['count']} in "
                       f"{window.total_seconds() / 3600:g}h: {r.get('reason')}")[:160],
            "artifact_rel": INCIDENTS_REL,
            "store": "data/runtime",
            "detected_at": d["at"].replace(minute=0, second=0, microsecond=0).isoformat(),
        })
    return out, f"effect_ownership:ok:{len(out)}"
