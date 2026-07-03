"""End-to-end symbol journey: watchlist → governor → research → outcome → feedback."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse_ts(val: Any) -> str | None:
    if val is None:
        return None
    try:
        if isinstance(val, datetime):
            return val.astimezone(timezone.utc).isoformat()
        return str(val).replace("Z", "+00:00")[:32]
    except Exception:
        return str(val)[:32] if val else None


def _timeline_sort(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(e: dict[str, Any]) -> str:
        return str(e.get("at") or "")
    return sorted(events, key=key, reverse=True)


def _load_bus_symbol(sym: str) -> dict[str, Any]:
    try:
        from lib.hermes_outcome_bus.bus import read_outcome_bus
        bus = read_outcome_bus() or {}
        row = dict((bus.get("by_symbol") or {}).get(sym) or {})
        lc = (bus.get("lifecycle") or {})
        wl = (lc.get("watchlist") or {}).get("symbols") or {}
        hl = (lc.get("holdings") or {}).get("symbols") or {}
        if sym in wl:
            row["watchlist_lifecycle"] = wl[sym]
        if sym in hl:
            row["holdings_lifecycle"] = hl[sym]
        return row
    except Exception:
        return {}


def _load_watchlist_state(sym: str) -> dict[str, Any]:
    try:
        from lib.hermes_scope_governor.watchlist_lifecycle import load_lifecycle_state
        state = load_lifecycle_state()
        return dict((state.get("symbols") or {}).get(sym) or {})
    except Exception:
        return {}


def _load_holdings_state(sym: str) -> dict[str, Any]:
    try:
        from lib.hermes_holdings_lifecycle.holdings_lifecycle import load_holdings_lifecycle_state
        state = load_holdings_lifecycle_state()
        return dict((state.get("holdings") or {}).get(sym) or {})
    except Exception:
        return {}


def _audit_tail_for_symbol(sym: str, limit: int = 15) -> list[dict[str, Any]]:
    try:
        from lib.hermes_scope_governor.watchlist_lifecycle import load_lifecycle_audit_tail
        rows = load_lifecycle_audit_tail(200)
        return [r for r in rows if str(r.get("symbol") or "").upper() == sym][:limit]
    except Exception:
        return []


def _query_governor_audit(sym: str, limit: int = 12) -> list[dict[str, Any]]:
    try:
        from db_adapter import _db_query, USE_DB
        if not USE_DB:
            return []
        rows = _db_query(
            """SELECT run_id, symbol, action, from_tier, to_tier, reason, created_at
               FROM scope_governor_audit
               WHERE UPPER(symbol) = %s AND symbol <> '__BUS__'
               ORDER BY created_at DESC LIMIT %s""",
            (sym, limit),
        ) or []
        return [dict(r) for r in rows]
    except Exception:
        return []


def _query_outcome_ledger(sym: str, limit: int = 15) -> list[dict[str, Any]]:
    try:
        from db_adapter import _db_query, USE_DB
        if not USE_DB:
            return []
        rows = _db_query(
            """SELECT subject_type, subject_id, verdict, direction, emitted_at, graded_at,
                      realized_r, outcome_ret_5d, actioned
               FROM hermes_outcome_ledger
               WHERE UPPER(symbol) = %s
               ORDER BY COALESCE(graded_at, emitted_at) DESC NULLS LAST
               LIMIT %s""",
            (sym, limit),
        ) or []
        return [dict(r) for r in rows]
    except Exception:
        return []


def _query_research_count(sym: str, days: int = 30) -> int:
    try:
        from db_adapter import _db_query, USE_DB
        if not USE_DB:
            return 0
        rows = _db_query(
            """SELECT count(*) AS n FROM hermes_external_research
               WHERE UPPER(symbol) = %s
                 AND created_at > NOW() - make_interval(days => %s)
                 AND recommendation IS NOT NULL AND recommendation NOT LIKE '[%%'""",
            (sym, days),
        ) or []
        return int((rows[0] or {}).get("n") or 0) if rows else 0
    except Exception:
        return 0


def _query_trades(sym: str, limit: int = 8) -> list[dict[str, Any]]:
    try:
        from db_adapter import _db_query, USE_DB
        if not USE_DB:
            return []
        rows = _db_query(
            """SELECT id, status, lifecycle_state, realized_pnl, closed_at, opened_at, strategy_id
               FROM paper_trades
               WHERE UPPER(symbol) = %s
               ORDER BY COALESCE(closed_at, opened_at) DESC NULLS LAST
               LIMIT %s""",
            (sym, limit),
        ) or []
        return [dict(r) for r in rows]
    except Exception:
        return []


def _build_timeline(
    sym: str,
    gov_audit: list[dict[str, Any]],
    wl_audit: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for g in gov_audit:
        events.append({
            "at": _parse_ts(g.get("created_at")),
            "kind": "governor_tier",
            "source": "scope_governor_audit",
            "summary": f"{g.get('from_tier')}→{g.get('to_tier')} ({g.get('action')})",
            "detail": str(g.get("reason") or "")[:200],
        })
    for a in wl_audit:
        act = a.get("action")
        if act == "blocked_promotion":
            events.append({
                "at": _parse_ts(a.get("at")),
                "kind": "watchlist_gate_blocked",
                "source": "hermes_watchlist_lifecycle_audit",
                "summary": f"promotion blocked health={a.get('health_score')}",
                "detail": str(a.get("reason") or "")[:200],
            })
        elif act == "manual_override":
            events.append({
                "at": _parse_ts(a.get("at")),
                "kind": "watchlist_override",
                "source": "hermes_watchlist_lifecycle_audit",
                "summary": f"stage→{a.get('stage')}",
                "detail": str(a.get("reason") or "")[:200],
            })
    for l in ledger:
        events.append({
            "at": _parse_ts(l.get("graded_at") or l.get("emitted_at")),
            "kind": "outcome_graded",
            "source": "hermes_outcome_ledger",
            "summary": f"{l.get('subject_type')} {l.get('verdict') or 'pending'}",
            "detail": f"direction={l.get('direction')} r={l.get('realized_r')}",
        })
    for t in trades:
        events.append({
            "at": _parse_ts(t.get("closed_at") or t.get("opened_at")),
            "kind": "paper_trade",
            "source": "paper_trades",
            "summary": f"{t.get('lifecycle_state') or t.get('status')} pnl={t.get('realized_pnl')}",
            "detail": str(t.get("strategy_id") or "")[:80],
        })
    return _timeline_sort(events)[:40]


def build_symbol_journey(symbol: str) -> dict[str, Any]:
    """Assemble closed-loop trace for one symbol."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return {"ok": False, "reason": "symbol_required"}

    bus_sym = _load_bus_symbol(sym)
    wl = _load_watchlist_state(sym)
    hl = _load_holdings_state(sym)
    gov_audit = _query_governor_audit(sym)
    wl_audit = _audit_tail_for_symbol(sym)
    ledger = _query_outcome_ledger(sym)
    trades = _query_trades(sym)
    research_n = _query_research_count(sym)
    timeline = _build_timeline(sym, gov_audit, wl_audit, ledger, trades)

    feedback = None
    try:
        from lib.hermes_outcome_bus.bus import governor_feedback_index, read_outcome_bus
        bus = read_outcome_bus() or {}
        fb = (governor_feedback_index(bus) or {}).get(sym)
        if fb:
            feedback = fb
    except Exception:
        pass

    return {
        "ok": True,
        "symbol": sym,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "scope_tier": wl.get("scope_tier") or bus_sym.get("scope_tier"),
            "watchlist_stage": wl.get("lifecycle_stage") or (bus_sym.get("watchlist_lifecycle") or {}).get("lifecycle_stage"),
            "holdings_stage": hl.get("lifecycle_stage") or (bus_sym.get("holdings_lifecycle") or {}).get("lifecycle_stage"),
            "watchlist_health": wl.get("health_score") or (bus_sym.get("watchlist_lifecycle") or {}).get("health_score"),
            "holdings_health": hl.get("health_score") or (bus_sym.get("holdings_lifecycle") or {}).get("health_score"),
            "outcome_gate": bus_sym.get("gate") or wl.get("outcome_gate"),
            "bus_n": bus_sym.get("n"),
            "bus_lift": bus_sym.get("lift"),
            "research_rows_30d": research_n,
            "timeline_events": len(timeline),
        },
        "watchlist_lifecycle": wl or bus_sym.get("watchlist_lifecycle"),
        "holdings_lifecycle": hl or bus_sym.get("holdings_lifecycle"),
        "outcome_bus": bus_sym,
        "governor_feedback": feedback,
        "governor_audit": gov_audit,
        "watchlist_audit": wl_audit,
        "outcome_ledger": ledger,
        "paper_trades": trades,
        "timeline": timeline,
        "trace_links": {
            "outcome_bus": f"/api/v2/hermes/outcome-bus?symbol={sym}",
            "scope_governor": f"/api/v2/hermes/scope-governor?symbol={sym}",
            "symbol_journey": f"/api/v2/hermes/symbol-journey?symbol={sym}",
        },
    }