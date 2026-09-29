"""Operator "watchlist and research" asks are monitored and researched.

An active ticker directive created by the operator, with Hermes enabled, is a
research obligation until a real research row exists after that directive.
Those names sort ahead of the ordinary watchlist and keep a small reserved
slot so a full run budget cannot drop them. Advisory only. No orders.
"""

from __future__ import annotations

OPERATOR_ACTORS = ("openclaw", "operator")
COUNTING_RESEARCH_STATUSES = ("promoted", "reviewed", "staged")
COUNTING_EXTERNAL_STATUSES = ("complete", "ok", "sent", "success")
OPERATOR_RESEARCH_RESERVE = 10
OPERATOR_RESEARCH_SCORE = 1_000_000.0
# The sweep's $0.30 process cap is often full by afternoon. This extra,
# still inside the global daily cap, is only for a name that still owes research.
OPERATOR_RESEARCH_USD_RESERVE = 0.05

OWED_SQL = """
SELECT DISTINCT UPPER(d.spec->>'symbol') AS symbol
FROM watch_directives d
WHERE d.status = 'active'
  AND d.kind = 'ticker'
  AND COALESCE(d.hermes_enabled, true)
  AND LOWER(COALESCE(d.created_by, 'operator')) = ANY(%s)
  AND UPPER(COALESCE(d.spec->>'symbol', '')) <> ''
  AND NOT EXISTS (
        SELECT 1 FROM hermes_research_intelligence r
        WHERE UPPER(r.symbol) = UPPER(d.spec->>'symbol')
          AND r.created_at >= d.created_at
          AND r.status = ANY(%s)
  )
  AND NOT EXISTS (
        SELECT 1 FROM hermes_external_research e
        WHERE UPPER(e.symbol) = UPPER(d.spec->>'symbol')
          AND e.created_at >= d.created_at
          AND e.status = ANY(%s)
          AND COALESCE(e.recommendation, '') !~ '^\\['
  )
"""

_WATCH_SQL = """
SELECT 1 AS hit FROM watch_directives
WHERE status = 'active' AND kind = 'ticker'
  AND COALESCE(hermes_enabled, true)
  AND LOWER(COALESCE(created_by, 'operator')) = ANY(%s)
  AND UPPER(spec->>'symbol') = %s
LIMIT 1
"""


def _symbol_of(row) -> str:
    if isinstance(row, dict):
        raw = row.get("symbol")
        if raw is None and row:
            raw = next(iter(row.values()))
    else:
        raw = row[0] if row else ""
    return str(raw or "").upper().strip()


def fetch_operator_research_owed(query) -> set[str]:
    """Symbols whose operator watch still has no research written after the ask."""
    try:
        rows = (
            query(
                OWED_SQL,
                (list(OPERATOR_ACTORS), list(COUNTING_RESEARCH_STATUSES), list(COUNTING_EXTERNAL_STATUSES)),
            )
            or []
        )
    except Exception:
        return set()
    return {sym for sym in (_symbol_of(r) for r in rows) if sym}


def symbol_research_owed(symbol: str, query=None) -> bool:
    """True when this symbol is an operator watch that still has no research row."""
    sym = str(symbol or "").upper().strip()
    if not sym:
        return False
    if query is None:
        try:
            from db_adapter import _execute

            query = lambda sql, params=(): _execute(sql, params, fetch="all") or []
        except Exception:
            return False
    try:
        rows = (
            query(
                OWED_SQL + "\n  AND UPPER(d.spec->>'symbol') = %s\n",
                (
                    list(OPERATOR_ACTORS),
                    list(COUNTING_RESEARCH_STATUSES),
                    list(COUNTING_EXTERNAL_STATUSES),
                    sym,
                ),
            )
            or []
        )
    except Exception:
        return False
    return bool(rows)


def cap_for_operator_research(cfg: dict, *, reserve: float = OPERATOR_RESEARCH_USD_RESERVE) -> dict:
    """Copy of the process cap with the operator-research reserve added. Does not mutate cfg."""
    out = dict(cfg or {})
    try:
        base = float(out.get("daily_cost_cap_usd") or 0)
    except (TypeError, ValueError):
        return out
    if base <= 0:
        return out
    out["daily_cost_cap_usd"] = base + float(reserve)
    return out


def research_reserve_config(cfg, symbol, *, query=None):
    """Use the reserve only while this symbol's operator research is still owed."""
    try:
        if not symbol_research_owed(symbol, query=query):
            return cfg
        return cap_for_operator_research(cfg)
    except Exception:
        return cfg


def lookup_operator_watch(symbol: str, query=None) -> bool:
    """True when an operator ticker directive is actively watching this symbol."""
    sym = str(symbol or "").upper().strip()
    if not sym:
        return False
    if query is None:
        try:
            from db_adapter import _execute

            query = lambda sql, params=(): _execute(sql, params, fetch="all") or []
        except Exception:
            return False
    try:
        rows = query(_WATCH_SQL, (list(OPERATOR_ACTORS), sym)) or []
    except Exception:
        return False
    return bool(rows)


def annotate_operator_watch(memberships, on_operator_watch: bool) -> list:
    """A watched name is material research membership, even with no thesis yet."""
    out = [str(m) for m in (memberships or []) if str(m or "").strip()]
    have = {m.upper() for m in out}
    if on_operator_watch and not ({"WATCH", "WATCHLIST"} & have):
        out.append("WATCH")
    return out


def pin_operator_research(due, owed) -> list:
    """Put operator-owed names first. A name missing from `due` is still included."""
    owed_u = {str(s).upper().strip() for s in (owed or []) if str(s or "").strip()}
    present: set[str] = set()
    rows = []
    for item in due or []:
        row = dict(item)
        sym = str(row.get("symbol") or "").upper().strip()
        row["symbol"] = sym
        if sym in owed_u:
            row["operator_research_owed"] = True
            row["score"] = float(row.get("score") or 0) + OPERATOR_RESEARCH_SCORE
        present.add(sym)
        rows.append(row)
    for sym in sorted(owed_u - present):
        rows.append(
            {
                "symbol": sym,
                "tier": "T1-WATCH",
                "rank": None,
                "age_days": 9999,
                "catalyst": False,
                "score": OPERATOR_RESEARCH_SCORE,
                "operator_research_owed": True,
            }
        )
    rows.sort(key=lambda r: float(r.get("score") or 0), reverse=True)
    return rows


def external_slot(
    *, owed: bool, spent: int, budget: int, reserved_used: int, reserve: int = OPERATOR_RESEARCH_RESERVE
) -> str:
    """How this external call is paid for: reserve, shared budget, or blocked.

    The reserve is only for an operator watch that still owes research. It does
    not consume the run's shared budget. Once the reserve is used, further owed
    names use the shared budget like every other name.
    """
    if owed and reserved_used < reserve:
        return "reserve"
    if spent >= budget:
        return "blocked"
    return "budget"
