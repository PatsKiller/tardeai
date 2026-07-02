"""Watchlist / Hermes resource prioritization — top-N focus off-hours (operator 2026-07-02).

Off-hours work concentrates on:
  • Daily-priority symbols (always): holdings, active proposals, BUY/STRONG_BUY/START,
    pipeline-active watchlist names, operator directives
  • Plus Hermes rank <= TOP_N (default 200) for the broader actionable window
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

# Active broker/paper proposals — always daily-priority.
PROPOSAL_ACTIVE_STATUSES = (
    "PENDING", "APPROVED", "APPROVED_FOR_PAPER_TEST", "MODIFIED", "BROKER_SUBMITTED",
)

# Buy-side CIO / card ratings that bypass the rank tail (incl. START = ready-to-enter).
DAILY_PRIORITY_BUY_RECS = frozenset({
    "buy", "strong_buy", "strongbuy", "add", "add_on_pullback", "accumulate",
    "start", "wait_for_pullback", "wait_pullback",
})

# SQL IN-list for legacy callers (spaces preserved for direct UPPER() match).
DAILY_PRIORITY_BUY_RECS_SQL = (
    "BUY", "STRONG_BUY", "STRONG BUY", "ADD", "ADD_ON_PULLBACK", "ADD ON PULLBACK",
    "ACCUMULATE", "START", "WAIT_FOR_PULLBACK", "WAIT FOR PULLBACK",
)


def _norm_rec(raw: str | None) -> str | None:
    if not raw:
        return None
    r = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    if r == "strongbuy":
        return "strong_buy"
    return r if r in DAILY_PRIORITY_BUY_RECS else None


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


def holdings_list(project_root: Path | None = None) -> list[str]:
    return sorted(load_holding_symbols(project_root))


def sql_daily_priority_exists(symbol_sql: str = "j.symbol") -> str:
    """Parameterized SQL fragment: True when symbol has daily priority.

    Binds (in order): holdings[], proposal_statuses[], buy_recs[], buy_recs[] again for synthesis.
    """
    sym = symbol_sql
    return f"""(
        {sym} = ANY(%s)
        OR EXISTS (SELECT 1 FROM paper_trade_proposals p
                   WHERE UPPER(p.symbol) = UPPER({sym}) AND p.status = ANY(%s))
        OR EXISTS (SELECT 1 FROM watchlist_items wi
                   WHERE UPPER(wi.symbol) = UPPER({sym}) AND wi.in_directive_watch)
        OR EXISTS (SELECT 1 FROM watchlist_items wi
                   WHERE UPPER(wi.symbol) = UPPER({sym}) AND wi.status = 'active')
        OR EXISTS (SELECT 1 FROM watchlist_research_cards rc
                   WHERE UPPER(rc.symbol) = UPPER({sym})
                     AND UPPER(REPLACE(REPLACE(rc.latest_recommendation, ' ', '_'), '-', '_')) = ANY(%s))
        OR EXISTS (SELECT 1 FROM watchlist_final_synthesis fs
                   WHERE UPPER(fs.symbol) = UPPER({sym})
                     AND UPPER(REPLACE(REPLACE(fs.recommendation, ' ', '_'), '-', '_')) = ANY(%s))
    )"""


def daily_priority_sql_params(holdings: list[str] | None = None,
                              project_root: Path | None = None) -> tuple:
    """Standard bind tuple for sql_daily_priority_exists()."""
    h = holdings if holdings is not None else holdings_list(project_root)
    buy = list(DAILY_PRIORITY_BUY_RECS)
    return (h, list(PROPOSAL_ACTIVE_STATUSES), buy, buy)


def sql_off_hours_scope(symbol_sql: str = "j.symbol") -> str:
    """Off-hours job/symbol scope: daily priority OR Hermes rank <= TOP_N."""
    daily = sql_daily_priority_exists(symbol_sql)
    return f"""(
        {daily}
        OR EXISTS (SELECT 1 FROM watchlist_items wi
                   WHERE UPPER(wi.symbol) = UPPER({symbol_sql})
                     AND wi.hermes_rank IS NOT NULL AND wi.hermes_rank <= %s)
    )"""


def off_hours_scope_params(holdings: list[str] | None = None,
                           project_root: Path | None = None,
                           top_n: int | None = None) -> tuple:
    return (*daily_priority_sql_params(holdings, project_root), top_n or WATCHLIST_TOP_N)


def sql_job_priority_case(symbol_sql: str = "j.symbol") -> str:
    """ORDER BY tier: directive · holdings · proposals · buy-rated · top-N · active · tail."""
    sym = symbol_sql
    buy = ", ".join(f"'{r}'" for r in DAILY_PRIORITY_BUY_RECS_SQL)
    return f"""(CASE
        WHEN EXISTS (SELECT 1 FROM watchlist_items wi
                     WHERE UPPER(wi.symbol) = UPPER({sym}) AND wi.in_directive_watch) THEN 0
        WHEN {sym} = ANY(%s) THEN 1
        WHEN EXISTS (SELECT 1 FROM paper_trade_proposals p
                     WHERE UPPER(p.symbol) = UPPER({sym}) AND p.status = ANY(%s)) THEN 2
        WHEN EXISTS (SELECT 1 FROM watchlist_research_cards rc
                     WHERE UPPER(rc.symbol) = UPPER({sym})
                       AND UPPER(rc.latest_recommendation) IN ({buy})) THEN 3
        WHEN EXISTS (SELECT 1 FROM watchlist_final_synthesis fs
                     WHERE UPPER(fs.symbol) = UPPER({sym})
                       AND UPPER(fs.recommendation) IN ({buy})) THEN 3
        WHEN EXISTS (SELECT 1 FROM watchlist_items wi
                     WHERE UPPER(wi.symbol) = UPPER({sym})
                       AND wi.hermes_rank IS NOT NULL AND wi.hermes_rank <= %s) THEN 4
        WHEN EXISTS (SELECT 1 FROM watchlist_items wi
                     WHERE UPPER(wi.symbol) = UPPER({sym}) AND wi.status = 'active') THEN 5
        ELSE 6 END)"""


def job_priority_params(holdings: list[str] | None = None,
                        project_root: Path | None = None,
                        top_n: int | None = None) -> tuple:
    h = holdings if holdings is not None else holdings_list(project_root)
    return (h, list(PROPOSAL_ACTIVE_STATUSES), top_n or WATCHLIST_TOP_N)


def load_daily_priority_symbols(cur, project_root: Path | None = None) -> set[str]:
    """All symbols that qualify for daily priority (for alert scoping without rank)."""
    holdings = holdings_list(project_root)
    buy = list(DAILY_PRIORITY_BUY_RECS)
    cur.execute(f"""SELECT DISTINCT UPPER(wi.symbol) AS symbol
                    FROM watchlist_items wi
                    WHERE wi.status IN ('active','researched')
                      AND {sql_daily_priority_exists('wi.symbol')}""",
                daily_priority_sql_params(holdings, project_root))
    return {str(r[0]).upper() for r in cur.fetchall() if r and r[0]}


def rank_in_scope(rank: int | None, top_n: int | None = None,
                  symbol: str | None = None, daily_symbols: set[str] | None = None) -> bool:
    """True when symbol is daily-priority or Hermes rank is within the actionable window."""
    if symbol and daily_symbols and str(symbol).upper() in daily_symbols:
        return True
    if rank is None:
        return False
    return int(rank) <= (top_n or WATCHLIST_TOP_N)


def rank_alert_worthy(cur_rank: int | None, prev_rank: int | None, top_n: int | None = None,
                      symbol: str | None = None, daily_symbols: set[str] | None = None) -> bool:
    """Suppress tail rank-jump noise; alert daily-priority and top-N names."""
    if symbol and daily_symbols and str(symbol).upper() in daily_symbols:
        return True
    n = top_n or WATCHLIST_TOP_N
    if cur_rank is None:
        return False
    if int(cur_rank) <= n:
        return True
    if prev_rank is not None and int(prev_rank) > n >= int(cur_rank):
        return True
    return False


def is_buy_side_rating(raw: str | None) -> bool:
    return _norm_rec(raw) is not None