"""Agent Opinion — Data Broker read model over watchlist_agent_results + agent_debate_log.

Proposed registry domain ``agent_opinion`` (docs/implementation/sot/phase4_registry_patch.json).
Two stores answer "what did the agents say":

  watchlist_agent_results  — per-symbol Maria/Steph/Risk/Tax recommendations (alive: last
                             row 2026-09-12 at measurement)
  agent_debate_log         — multi-agent debates (DEAD: last row 2026-05-05, 9 rows, 131d)

The Agents hub rendered both as current. This projection carries a separate
envelope per store so the dead one is declared (``gap.kind == "no_producer"``) while
the live one keeps its age. Composes the existing ``agent_results`` module for the
per-symbol read; adds the roster/debate summaries the hub needs.

Zero provider calls. Read-only.
"""
from __future__ import annotations

from typing import Any

from lib.data_broker.envelope import envelope

DOMAIN_RESULTS = "agent_opinion"
DOMAIN_DEBATES = "agent_debate"

#: Until the registry patch lands these two domains are not in
#: config/data_source_authority.json, so their windows are declared here and
#: passed explicitly. Same numbers as the patch.
FALLBACK_WINDOWS = {DOMAIN_RESULTS: 48.0, DOMAIN_DEBATES: 168.0}

ROSTER_SQL = """
        SELECT agent, count(*) as total,
               count(*) FILTER (WHERE created_at > NOW() - INTERVAL '30 days') as total_30d,
               count(CASE WHEN recommendation IN ('BUY','ADD','STRONG_BUY') THEN 1 END) as buy_count,
               count(CASE WHEN recommendation IN ('SELL','TRIM','REDUCE') THEN 1 END) as sell_count,
               count(CASE WHEN recommendation IN ('HOLD','NEUTRAL') THEN 1 END) as hold_count,
               avg(
                 CASE
                   WHEN confidence IS NULL THEN NULL
                   WHEN confidence > 100 THEN NULL
                   WHEN confidence > 1 THEN LEAST(1.0, confidence / 100.0)
                   ELSE LEAST(1.0, GREATEST(0.0, confidence))
                 END
               ) as avg_confidence,
               max(created_at) as latest
        FROM watchlist_agent_results
        GROUP BY agent ORDER BY total DESC
"""

DEBATES_SQL = """
        SELECT count(*) as cnt,
               AVG(consensus_score) as avg_consensus,
               max(created_at) as latest
        FROM agent_debate_log
        WHERE created_at > NOW() - INTERVAL '7 days'
"""

DEBATES_LAST_SQL = "SELECT max(created_at) AS latest, count(*) AS n FROM agent_debate_log"


def _win(domain: str, registry) -> float | None:
    from lib.data_broker.envelope import registry_spec
    spec = registry_spec(domain, registry=registry)
    return spec.get("stale_after_hours") if spec.get("class") else FALLBACK_WINDOWS.get(domain)


def get_agent_roster(db_query, *, now=None, registry=None) -> dict[str, Any]:
    """Per-agent all-time + 30d counts from watchlist_agent_results, with envelope."""
    rows: list[dict[str, Any]] = []
    error = None
    try:
        rows = db_query(ROSTER_SQL) or []
    except Exception as e:  # noqa: BLE001
        error = str(e)[:200]
    latest = None
    for r in rows:
        l = r.get("latest")
        if l is not None and (latest is None or l > latest):
            latest = l
    env = envelope(DOMAIN_RESULTS, latest, now=now, registry=registry,
                   stale_after_hours=_win(DOMAIN_RESULTS, registry),
                   source={"table": "watchlist_agent_results", "writer": "scripts/watchlist_agent_worker.py"})
    out = {"ok": error is None, "agents": rows, "count_source": "watchlist_agent_results", "provider_calls": 0}
    if error:
        out["error"] = error
    out.update(env)
    return out


def get_debate_summary(db_query, *, now=None, registry=None) -> dict[str, Any]:
    """7-day debate count/consensus from agent_debate_log, with envelope.

    ``as_of`` is the table's newest row EVER (not the 7-day window's), so a dead
    feed reports its last real as_of instead of None — the operator sees "last
    debate 2026-05-05", not an empty cell.
    """
    win: dict[str, Any] = {"cnt": 0, "avg_consensus": None}
    last = None
    error = None
    try:
        rows = db_query(DEBATES_SQL) or []
        if rows:
            win = dict(rows[0])
        lr = db_query(DEBATES_LAST_SQL, fetch="one") or {}
        last = lr.get("latest")
    except Exception as e:  # noqa: BLE001
        error = str(e)[:200]
    env = envelope(DOMAIN_DEBATES, last, now=now, registry=registry,
                   stale_after_hours=_win(DOMAIN_DEBATES, registry),
                   source={"table": "agent_debate_log", "writer": None})
    out = {"ok": error is None, "count": win.get("cnt", 0) or 0, "avg_consensus": win.get("avg_consensus"),
           "provider_calls": 0}
    if error:
        out["error"] = error
    out.update(env)
    return out


def get_agent_opinion(db_query, symbols: list[str] | None = None, *, days: int = 14, now=None, registry=None) -> dict[str, Any]:
    """Per-symbol agent recommendations (composes agent_results) + both envelopes.

    {ok, by_symbol: {SYM: [...]}, roster: <get_agent_roster>, debates: <get_debate_summary>, <envelope of results>}
    """
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    if symbols:
        try:
            from lib.data_broker.agent_results import get_agent_results
            by_symbol = get_agent_results(db_query, symbols, days=days)
        except Exception:  # noqa: BLE001
            by_symbol = {}
    roster = get_agent_roster(db_query, now=now, registry=registry)
    debates = get_debate_summary(db_query, now=now, registry=registry)
    out = {"ok": roster.get("ok", False), "by_symbol": by_symbol, "roster": roster, "debates": debates,
           "provider_calls": 0}
    out.update({k: roster[k] for k in ("schema", "as_of", "age_hours", "source", "stale", "stale_after_hours") if k in roster})
    if "gap" in roster:
        out["gap"] = roster["gap"]
    return out
