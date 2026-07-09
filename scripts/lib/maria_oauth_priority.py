"""Maria OAuth priority tier — holdings, top WAIT setups, manual refresh only."""
from __future__ import annotations

import os

MARIA_OAUTH_PROCESS_ID = "watchlist_maria_priority"
MARIA_OAUTH_DAILY_CAP = int(os.environ.get("MARIA_OAUTH_DAILY_CAP", "80"))
MARIA_OAUTH_RUN_CAP = int(os.environ.get("MARIA_OAUTH_RUN_CAP", "12"))
WAIT_SETUP_LIMIT = int(os.environ.get("MARIA_OAUTH_WAIT_LIMIT", "3"))
WAIT_SETUP_HOURS = int(os.environ.get("MARIA_OAUTH_WAIT_HOURS", "48"))

MANUAL_SUBMITTED_FROM = frozenset({
    "watchlist_requeue",
    "holdings_change_trigger",
    "api",
    "command_center",
})

TIME_SENSITIVE_REQUEST_TYPES = frozenset({
    "proposal_review", "full_analysis", "research_gap", "event",
})


def is_manual_refresh(
    submitted_from: str | None,
    *,
    priority: int | None = None,
    request_type: str | None = None,
) -> bool:
    src = (submitted_from or "").strip().lower()
    if src in MANUAL_SUBMITTED_FROM:
        if src == "command_center":
            try:
                p = int(priority) if priority is not None else 99
            except (TypeError, ValueError):
                p = 99
            rt = (request_type or "").strip().lower()
            return p <= 1 or rt in TIME_SENSITIVE_REQUEST_TYPES
        return True
    try:
        return int(priority) == 0
    except (TypeError, ValueError):
        return False


def maria_priority_tier(
    symbol: str | None,
    *,
    portfolio_symbols: frozenset[str] | set[str],
    wait_symbols: frozenset[str] | set[str],
    submitted_from: str | None = None,
    priority: int | None = None,
    request_type: str | None = None,
) -> bool:
    sym = (symbol or "").upper().strip()
    if not sym:
        return False
    if sym in portfolio_symbols:
        return True
    if sym in wait_symbols:
        return True
    return is_manual_refresh(submitted_from, priority=priority, request_type=request_type)