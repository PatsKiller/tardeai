#!/usr/bin/env python3
"""Read-only watchlist_agent_jobs baseline. Never prints secrets."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def main() -> int:
    from db_adapter import USE_DB, _execute
    out = {"as_of": datetime.now(timezone.utc).isoformat(), "ok": False}
    if not USE_DB:
        out["error"] = "db_unavailable"
        print(json.dumps(out, default=str))
        return 1
    by_status = {}
    for row in _execute("SELECT status, COUNT(*) FROM watchlist_agent_jobs GROUP BY status", fetch="all") or []:
        if isinstance(row, dict):
            by_status[str(list(row.values())[0])] = int(list(row.values())[1] or 0)
        else:
            by_status[str(row[0])] = int(row[1] or 0)
    def _n(sql, params=None):
        row = _execute(sql, params, fetch="one")
        if not row:
            return 0
        return int(row[0] if not isinstance(row, dict) else list(row.values())[0] or 0)

    oldest = _execute("SELECT MIN(created_at) FROM watchlist_agent_jobs WHERE status='queued'", fetch="one")
    oldest_at = None
    if oldest:
        oldest_at = str(oldest[0] if not isinstance(oldest, dict) else list(oldest.values())[0])
    by_agent = {}
    for row in _execute("SELECT requested_agent, COUNT(*) FROM watchlist_agent_jobs WHERE status='queued' GROUP BY requested_agent", fetch="all") or []:
        if isinstance(row, dict):
            by_agent[str(list(row.values())[0])] = int(list(row.values())[1] or 0)
        else:
            by_agent[str(row[0])] = int(row[1] or 0)
    out.update({
        "ok": True,
        "queued": int(by_status.get("queued") or 0),
        "by_status": by_status,
        "maria_queued": int(by_agent.get("maria") or 0),
        "by_agent_queued": by_agent,
        "oldest_queued": oldest_at,
        "created_today": _n("SELECT COUNT(*) FROM watchlist_agent_jobs WHERE created_at >= CURRENT_DATE"),
        "completed_today": _n("SELECT COUNT(*) FROM watchlist_agent_jobs WHERE status='completed' AND COALESCE(completed_at,created_at) >= CURRENT_DATE"),
        "failed_today": _n("SELECT COUNT(*) FROM watchlist_agent_jobs WHERE status='failed' AND COALESCE(completed_at,created_at) >= CURRENT_DATE"),
        "created_24h": _n("SELECT COUNT(*) FROM watchlist_agent_jobs WHERE created_at > NOW() - INTERVAL '24 hours'"),
        "completed_24h": _n("SELECT COUNT(*) FROM watchlist_agent_jobs WHERE status='completed' AND COALESCE(completed_at,created_at) > NOW() - INTERVAL '24 hours'"),
        "failed_24h": _n("SELECT COUNT(*) FROM watchlist_agent_jobs WHERE status='failed' AND COALESCE(completed_at,created_at) > NOW() - INTERVAL '24 hours'"),
    })
    print(json.dumps(out, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
