"""Watchlist / Hermes resource prioritization — top-N focus off-hours (operator 2026-07-02).

Central constants for cron jobs that touch the ~3k-name watchlist tail: off-hours work should
concentrate on holdings, directives, active names, and Hermes rank <= TOP_N (default 200).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Env-tunable: operator-requested off-hours cap (2026-07-02).
WATCHLIST_TOP_N = int(os.getenv("WATCHLIST_OFF_HOURS_TOP_N", "200"))


def is_off_hours_et(now: datetime | None = None) -> bool:
    """True outside regular US equity session (Mon–Fri 09:30–16:00 ET) and all weekend."""
    now = now or datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    else:
        now = now.astimezone(ET)
    if now.weekday() >= 5:
        return True
    mins = now.hour * 60 + now.minute
    return not (9 * 60 + 30 <= mins < 16 * 60)


def off_hours_top_n(explicit_limit: int | None = None) -> int | None:
    """Return TOP_N when off-hours and no explicit --limit; else passthrough."""
    if explicit_limit is not None:
        return explicit_limit
    return WATCHLIST_TOP_N if is_off_hours_et() else None


def load_holding_symbols(project_root: Path | None = None) -> set[str]:
    root = project_root or Path(__file__).resolve().parent.parent.parent
    path = root / "data" / "portfolios" / "state" / "holdings.json"
    out: set[str] = set()
    try:
        data = json.loads(path.read_text())
        for h in data.get("holdings") or []:
            sym = str(h.get("symbol") or "").upper().strip()
            if sym and sym != "CASH" and sym.isalpha() and len(sym) <= 5:
                out.add(sym)
    except Exception:
        pass
    return out


def rank_in_scope(rank: int | None, top_n: int | None = None) -> bool:
    """True when Hermes rank is within the off-hours actionable window."""
    if rank is None:
        return False
    return int(rank) <= (top_n or WATCHLIST_TOP_N)


def rank_alert_worthy(cur_rank: int | None, prev_rank: int | None, top_n: int | None = None) -> bool:
    """Suppress tail rank-jump noise; still alert on names in top-N or crossing into it."""
    n = top_n or WATCHLIST_TOP_N
    if cur_rank is None:
        return False
    if int(cur_rank) <= n:
        return True
    if prev_rank is not None and int(prev_rank) > n >= int(cur_rank):
        return True
    return False


def holdings_list(project_root: Path | None = None) -> list[str]:
    return sorted(load_holding_symbols(project_root))