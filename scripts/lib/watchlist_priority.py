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
# Hermes audit 2026-07-02: cap market-hours scoring to same window (default on).
HERMES_SCORER_ALWAYS_CAP = os.getenv("HERMES_SCORER_ALWAYS_CAP", "1").strip() == "1"

# Active broker/paper proposals — always daily-priority.
PROPOSAL_ACTIVE_STATUSES = (
    "PENDING", "APPROVED", "APPROVED_FOR_PAPER_TEST", "MODIFIED", "BROKER_SUBMITTED",
)

# Decision-feeding job types with a 2h SLA (health_agent counts these as execution
# defects when starved). They must outrank the rolling research backlog regardless of
# symbol tier — a stream of scheduled_research on holdings otherwise starves them forever.
TIME_SENSITIVE_REQUEST_TYPES = (
    "proposal_review", "full_analysis", "research_gap", "event", "go_signal_review",
)


def sql_request_type_sla_case(request_type_sql: str = "j.request_type") -> str:
    """ORDER BY class: 0 = decision-feeding (SLA), 1 = background research/discovery."""
    return f"(CASE WHEN {request_type_sql} = ANY(%s) THEN 0 ELSE 1 END)"


def request_type_sla_params() -> tuple:
    return (list(TIME_SENSITIVE_REQUEST_TYPES),)


# Buy-side CIO / card ratings (proposal bridge, screener pins, job tier-3 head).
DAILY_PRIORITY_BUY_RECS = frozenset({
    "buy", "strong_buy", "strongbuy", "add", "add_on_pullback", "accumulate",
    "start", "wait_for_pullback", "wait_pullback",
})

# All CIO verdict tiers — daily news/enrichment priority (buy, hold, avoid, pullback, etc.).
DAILY_PRIORITY_RATED_RECS = frozenset({
    *DAILY_PRIORITY_BUY_RECS,
    "hold", "neutral", "research_more", "wait", "monitor", "watch",
    "avoid", "ignore", "sell", "trim", "reduce", "rebalance_trim", "strong_sell",
})

# SQL IN-list for legacy callers (spaces preserved for direct UPPER() match).
DAILY_PRIORITY_BUY_RECS_SQL = (
    "BUY", "STRONG_BUY", "STRONG BUY", "ADD", "ADD_ON_PULLBACK", "ADD ON PULLBACK",
    "ACCUMULATE", "START", "WAIT_FOR_PULLBACK", "WAIT FOR PULLBACK",
)

DAILY_PRIORITY_RATED_RECS_SQL = (
    *DAILY_PRIORITY_BUY_RECS_SQL,
    "HOLD", "NEUTRAL", "RESEARCH_MORE", "RESEARCH MORE", "WAIT", "MONITOR", "WATCH",
    "AVOID", "IGNORE", "SELL", "TRIM", "REDUCE", "REBALANCE_TRIM", "REBALANCE TRIM",
    "STRONG_SELL", "STRONG SELL",
)


def _norm_key(raw: str) -> str:
    r = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    if r == "strongbuy":
        return "strong_buy"
    if r == "researchmore":
        return "research_more"
    if r == "rebalancetrim":
        return "rebalance_trim"
    if r == "strongsell":
        return "strong_sell"
    return r


def _norm_rec(raw: str | None) -> str | None:
    if not raw:
        return None
    r = _norm_key(raw)
    return r if r in DAILY_PRIORITY_BUY_RECS else None


def _norm_rated_rec(raw: str | None) -> str | None:
    if not raw:
        return None
    r = _norm_key(raw)
    return r if r in DAILY_PRIORITY_RATED_RECS else None


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


def scoring_top_n(explicit_limit: int | None = None) -> int | None:
    """Cap for hermes_watchlist_scorer: daily-priority + top-N always when HERMES_SCORER_ALWAYS_CAP."""
    if explicit_limit is not None:
        return explicit_limit
    if HERMES_SCORER_ALWAYS_CAP or is_off_hours_et():
        return WATCHLIST_TOP_N
    return None


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

    Binds (in order): holdings[], proposal_statuses[], rated_recs[], rated_recs[] again for synthesis.
    """
    sym = symbol_sql
    return f"""(
        {sym} = ANY(%s)
        OR EXISTS (SELECT 1 FROM paper_trade_proposals p
                   WHERE UPPER(p.symbol) = UPPER({sym}) AND p.status = ANY(%s))
        OR EXISTS (SELECT 1 FROM watchlist_items wi_dp
                   WHERE UPPER(wi_dp.symbol) = UPPER({sym}) AND wi_dp.in_directive_watch)
        OR EXISTS (SELECT 1 FROM watchlist_items wi_dp
                   WHERE UPPER(wi_dp.symbol) = UPPER({sym}) AND wi_dp.status = 'active')
        OR EXISTS (SELECT 1 FROM watchlist_research_cards rc
                   WHERE UPPER(rc.symbol) = UPPER({sym})
                     AND UPPER(REPLACE(REPLACE(rc.latest_recommendation, ' ', '_'), '-', '_')) = ANY(%s))
        OR EXISTS (SELECT 1 FROM watchlist_final_synthesis fs
                   WHERE UPPER(fs.symbol) = UPPER({sym})
                     AND UPPER(REPLACE(REPLACE(fs.recommendation, ' ', '_'), '-', '_')) = ANY(%s))
        OR EXISTS (SELECT 1 FROM screener_find_pins sfp
                   WHERE UPPER(sfp.symbol) = UPPER({sym}) AND sfp.active = true)
    )"""


def sql_scoring_priority_exists(symbol_sql: str = "j.symbol") -> str:
    """Narrow priority for Hermes scorer cap / scope governor — no blanket status='active'."""
    sym = symbol_sql
    return f"""(
        {sym} = ANY(%s)
        OR EXISTS (SELECT 1 FROM paper_trade_proposals p
                   WHERE UPPER(p.symbol) = UPPER({sym}) AND p.status = ANY(%s))
        OR EXISTS (SELECT 1 FROM watchlist_items wi_dp
                   WHERE UPPER(wi_dp.symbol) = UPPER({sym}) AND wi_dp.in_directive_watch)
        OR EXISTS (SELECT 1 FROM watchlist_research_cards rc
                   WHERE UPPER(rc.symbol) = UPPER({sym})
                     AND UPPER(REPLACE(REPLACE(rc.latest_recommendation, ' ', '_'), '-', '_')) = ANY(%s))
        OR EXISTS (SELECT 1 FROM watchlist_final_synthesis fs
                   WHERE UPPER(fs.symbol) = UPPER({sym})
                     AND UPPER(REPLACE(REPLACE(fs.recommendation, ' ', '_'), '-', '_')) = ANY(%s))
    )"""


def scoring_priority_sql_params(holdings: list[str] | None = None,
                                project_root: Path | None = None) -> tuple:
    """Bind tuple for sql_scoring_priority_exists() — all CIO-rated verdicts."""
    h = holdings if holdings is not None else holdings_list(project_root)
    rated = sorted(r.upper() for r in DAILY_PRIORITY_RATED_RECS)
    return (h, list(PROPOSAL_ACTIVE_STATUSES), rated, rated)


def daily_priority_sql_params(holdings: list[str] | None = None,
                              project_root: Path | None = None) -> tuple:
    """Standard bind tuple for sql_daily_priority_exists()."""
    h = holdings if holdings is not None else holdings_list(project_root)
    # The SQL side compares UPPER(REPLACE(...)) — bind uppercase or rated tiers match nothing.
    rated = sorted(r.upper() for r in DAILY_PRIORITY_RATED_RECS)
    return (h, list(PROPOSAL_ACTIVE_STATUSES), rated, rated)


def sql_off_hours_scope(symbol_sql: str = "j.symbol") -> str:
    """Off-hours job/symbol scope: daily priority OR Hermes rank <= TOP_N."""
    daily = sql_daily_priority_exists(symbol_sql)
    return f"""(
        {daily}
        OR EXISTS (SELECT 1 FROM watchlist_items wi_dp
                   WHERE UPPER(wi_dp.symbol) = UPPER({symbol_sql})
                     AND wi_dp.hermes_rank IS NOT NULL AND wi_dp.hermes_rank <= %s)
    )"""


def off_hours_scope_params(holdings: list[str] | None = None,
                           project_root: Path | None = None,
                           top_n: int | None = None) -> tuple:
    return (*daily_priority_sql_params(holdings, project_root), top_n or WATCHLIST_TOP_N)


def sql_job_priority_case(symbol_sql: str = "j.symbol") -> str:
    """ORDER BY tier: directive · holdings · proposals · CIO-rated · top-N · active · tail."""
    sym = symbol_sql
    rated = ", ".join(f"'{r}'" for r in DAILY_PRIORITY_RATED_RECS_SQL)
    return f"""(CASE
        WHEN EXISTS (SELECT 1 FROM watchlist_items wi_dp
                     WHERE UPPER(wi_dp.symbol) = UPPER({sym}) AND wi_dp.in_directive_watch) THEN 0
        WHEN {sym} = ANY(%s) THEN 1
        WHEN EXISTS (SELECT 1 FROM paper_trade_proposals p
                     WHERE UPPER(p.symbol) = UPPER({sym}) AND p.status = ANY(%s)) THEN 2
        WHEN EXISTS (SELECT 1 FROM screener_find_pins sfp
                     WHERE UPPER(sfp.symbol) = UPPER({sym}) AND sfp.active = true) THEN 2
        WHEN EXISTS (SELECT 1 FROM watchlist_research_cards rc
                     WHERE UPPER(rc.symbol) = UPPER({sym})
                       AND UPPER(rc.latest_recommendation) IN ({rated})) THEN 3
        WHEN EXISTS (SELECT 1 FROM watchlist_final_synthesis fs
                     WHERE UPPER(fs.symbol) = UPPER({sym})
                       AND UPPER(fs.recommendation) IN ({rated})) THEN 3
        WHEN EXISTS (SELECT 1 FROM watchlist_items wi_dp
                     WHERE UPPER(wi_dp.symbol) = UPPER({sym})
                       AND wi_dp.hermes_rank IS NOT NULL AND wi_dp.hermes_rank <= %s) THEN 4
        WHEN EXISTS (SELECT 1 FROM watchlist_items wi_dp
                     WHERE UPPER(wi_dp.symbol) = UPPER({sym}) AND wi_dp.status = 'active') THEN 5
        ELSE 6 END)"""


def job_priority_params(holdings: list[str] | None = None,
                        project_root: Path | None = None,
                        top_n: int | None = None) -> tuple:
    h = holdings if holdings is not None else holdings_list(project_root)
    return (h, list(PROPOSAL_ACTIVE_STATUSES), top_n or WATCHLIST_TOP_N)


def load_daily_priority_symbols(cur, project_root: Path | None = None) -> set[str]:
    """All symbols that qualify for daily priority (for alert scoping without rank)."""
    holdings = holdings_list(project_root)
    cur.execute(f"""SELECT DISTINCT UPPER(wi.symbol) AS symbol
                    FROM watchlist_items wi
                    WHERE wi.status IN ('active','researched')
                      AND {sql_daily_priority_exists('wi.symbol')}""",
                daily_priority_sql_params(holdings, project_root))
    return {str(r[0]).upper() for r in cur.fetchall() if r and r[0]}


def load_alert_priority_symbols(cur, project_root: Path | None = None) -> set[str]:
    """ALERT eligibility — true CIO/operator priority, NOT every active watchlist row.

    Reuses sql_scoring_priority_exists (holdings, directives, active proposals,
    CIO-rated cards/synthesis). Passive status='active' inventory stays subject
    to the Hermes top-N window.
    """
    holdings = holdings_list(project_root)
    out = {str(s).upper() for s in holdings}
    try:
        cur.execute(f"""SELECT DISTINCT UPPER(wi.symbol) AS symbol
                        FROM watchlist_items wi
                        WHERE {sql_scoring_priority_exists('wi.symbol')}""",
                    scoring_priority_sql_params(holdings, project_root))
        out.update(str(r[0]).upper() for r in cur.fetchall() if r and r[0])
    except Exception:
        try:
            cur.connection.rollback()
        except Exception:
            pass
    return out


def rank_band(rank: int | None, top_n: int | None = None) -> str:
    """Material rank bands. Churn inside a band is not operator-pageable."""
    if rank is None:
        return "unknown"
    r = int(rank)
    n = top_n or WATCHLIST_TOP_N
    if r <= 20:
        return "top20"
    if r <= 50:
        return "top50"
    if r <= 100:
        return "top100"
    if r <= n:
        return "top200"
    return "outside"


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
    """Alert only on a material band change (enter/leave top-N or cross a band).

    `daily_symbols` used to exempt every active-watchlist name from top-N; that
    is no longer a rank-alert bypass. Holdings/CIO-priority still get score and
    factor alerts via rank_in_scope(); rank pages require a band change.
    """
    n = top_n or WATCHLIST_TOP_N
    cur_b = rank_band(cur_rank, n)
    prev_b = rank_band(prev_rank, n)
    if cur_b == "unknown":
        return False
    if cur_b == "outside" and prev_b == "outside":
        return False
    return cur_b != prev_b


def is_buy_side_rating(raw: str | None) -> bool:
    return _norm_rec(raw) is not None


def is_rated_verdict(raw: str | None) -> bool:
    """True for any CIO verdict tier (buy, hold, avoid, pullback, etc.)."""
    return _norm_rated_rec(raw) is not None