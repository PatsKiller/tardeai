"""Hermes research-quality gates — prior-research check for proposal fail-closed path."""
from __future__ import annotations

PRIOR_RESEARCH_WINDOW_DAYS = 30


def symbol_has_prior_research(cur, symbol: str, *, within_days: int = PRIOR_RESEARCH_WINDOW_DAYS) -> bool:
    """True when symbol has hermes_research_intelligence within the lookback window."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return False
    cur.execute(
        """SELECT 1 FROM hermes_research_intelligence
           WHERE UPPER(symbol) = %s
             AND created_at > NOW() - (%s || ' days')::interval
           LIMIT 1""",
        (sym, str(within_days)),
    )
    return cur.fetchone() is not None


def proposal_prior_research_blocked(cur, symbol: str, *, within_days: int = PRIOR_RESEARCH_WINDOW_DAYS) -> str | None:
    """Return a short reason when a new proposal should be deferred; None if allowed."""
    if symbol_has_prior_research(cur, symbol, within_days=within_days):
        return None
    return f"missing hermes_research_intelligence within {within_days}d"
