"""Fetch symbol-level signals consumed by the Scope Governor."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import SymbolSignals

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _hours_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    except Exception:
        return None


def load_open_scalp_symbols(project_root: Path | None = None) -> set[str]:
    root = project_root or PROJECT_ROOT
    try:
        from lib.momentum_scalp_swarm_state import read_json
        data = read_json("open_scalps.json", default={}) or {}
        out: set[str] = set()
        for row in data.get("scalps") or data.get("positions") or []:
            sym = str(row.get("symbol") or "").upper().strip()
            if sym:
                out.add(sym)
        return out
    except Exception:
        return set()


def load_regime_label(cur) -> str | None:
    try:
        cur.execute("SELECT regime_label FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def fetch_symbol_signals(cur, cfg: dict[str, Any], project_root: Path | None = None) -> dict[str, SymbolSignals]:
    """Build SymbolSignals for every active/researched watchlist symbol."""
    from watchlist_priority import PROPOSAL_ACTIVE_STATUSES, holdings_list

    root = project_root or PROJECT_ROOT
    holdings = set(holdings_list(root))
    scalps = load_open_scalp_symbols(root)
    s1 = cfg.get("tiers", {}).get("s1", {})
    entry = s1.get("entry", {})
    event_h = int(entry.get("catalyst_hours", 48))
    directive_h = int(entry.get("directive_hit_hours", 48))
    outcome_lookback_days = int((cfg.get("scoring") or {}).get("outcome_lookback_days", 90))

    cur.execute("""SELECT UPPER(symbol), MAX(hermes_composite_score), MIN(hermes_rank),
                          BOOL_OR(status='active')
                   FROM watchlist_items WHERE status IN ('active','researched')
                   GROUP BY UPPER(symbol)""")
    base = {r[0]: {"composite": r[1], "rank": r[2], "active": r[3], "sector": None} for r in cur.fetchall()}

    open_pos: set[str] = set()
    cur.execute("SELECT DISTINCT UPPER(symbol) FROM paper_trades WHERE status IN ('open','filled')")
    open_pos = {r[0] for r in cur.fetchall()}

    live_prop: set[str] = set()
    cur.execute("SELECT DISTINCT UPPER(symbol) FROM paper_trade_proposals WHERE status = ANY(%s)",
                (list(PROPOSAL_ACTIVE_STATUSES),))
    live_prop = {r[0] for r in cur.fetchall()}

    op_dir: set[str] = set()
    cur.execute("""SELECT DISTINCT UPPER(h.symbol)
                   FROM watch_directive_hits h
                   JOIN watch_directives d ON d.id = h.directive_id
                   WHERE d.status='active' AND d.kind='ticker'
                     AND d.created_by IN ('operator','operator_audit')""")
    op_dir = {r[0] for r in cur.fetchall()}

    catalyst: set[str] = set()
    cur.execute("""SELECT DISTINCT UPPER(symbol) FROM catalyst_events
                   WHERE created_at > NOW() - make_interval(hours => %s)""", (event_h,))
    catalyst = {r[0] for r in cur.fetchall()}

    directive_hit: set[str] = set()
    cur.execute("""SELECT DISTINCT UPPER(symbol) FROM watch_directive_hits
                   WHERE surfaced_at > NOW() - make_interval(hours => %s)""", (directive_h,))
    directive_hit = {r[0] for r in cur.fetchall()}

    event_pending: set[str] = set()
    try:
        cur.execute("""SELECT DISTINCT UPPER(symbol) FROM hermes_score_event_queue
                       WHERE processed_at IS NULL AND created_at > NOW() - interval '48 hours'""")
        event_pending = {r[0] for r in cur.fetchall()}
    except Exception:
        pass

    intel: dict[str, dict[str, Any]] = {}
    try:
        cur.execute("""SELECT UPPER(display_name), social_score, rvol, atr_value,
                              last_enriched, sector
                       FROM intelligence_entities
                       WHERE entity_type='ticker' AND active=true""")
        for r in cur.fetchall():
            intel[r[0]] = {
                "social_score": r[1], "rvol": r[2], "avg_volume": None, "atr_pct": r[3],
                "last_enriched": r[4], "sector": r[5],
            }
    except Exception:
        try:
            cur.connection.rollback()
        except Exception:
            pass

    outcomes: dict[str, dict[str, Any]] = {}
    try:
        cur.execute("""SELECT UPPER(symbol),
                              count(*) FILTER (WHERE verdict='hit') AS hits,
                              count(*) FILTER (WHERE verdict='miss') AS misses,
                              count(*) FILTER (WHERE verdict='neutral') AS neutral,
                              avg(realized_r) FILTER (WHERE realized_r IS NOT NULL) AS avg_r,
                              avg(CASE WHEN COALESCE(actioned::text,'') IN ('true','t','1','yes')
                                       THEN 1.0 ELSE 0.0 END) AS actioned_rate
                       FROM hermes_outcome_ledger
                       WHERE symbol IS NOT NULL
                         AND emitted_at > NOW() - make_interval(days => %s)
                         AND verdict IN ('hit','miss','neutral')
                       GROUP BY UPPER(symbol)""", (outcome_lookback_days,))
        for r in cur.fetchall():
            outcomes[r[0]] = {
                "hits": int(r[1] or 0), "misses": int(r[2] or 0), "neutral": int(r[3] or 0),
                "avg_r": float(r[4]) if r[4] is not None else None,
                "actioned_rate": float(r[5]) if r[5] is not None else None,
            }
    except Exception:
        try:
            cur.connection.rollback()
        except Exception:
            pass

    high_conv: set[str] = set()
    try:
        cur.execute("SELECT DISTINCT UPPER(symbol) FROM watchlist_items WHERE in_directive_watch=true")
        high_conv = {r[0] for r in cur.fetchall()}
    except Exception:
        pass

    out: dict[str, SymbolSignals] = {}
    for sym, meta in base.items():
        ie = intel.get(sym, {})
        oc = outcomes.get(sym, {})
        out[sym] = SymbolSignals(
            symbol=sym,
            is_holding=sym in holdings,
            is_open_position=sym in open_pos,
            is_live_proposal=sym in live_prop,
            is_operator_directive=sym in op_dir,
            is_open_scalp=sym in scalps,
            is_watchlist_active=bool(meta.get("active")),
            is_high_conviction_watch=sym in high_conv,
            hermes_composite=float(meta["composite"]) if meta.get("composite") is not None else None,
            hermes_rank=int(meta["rank"]) if meta.get("rank") is not None else None,
            has_fresh_catalyst=sym in catalyst,
            has_fresh_directive_hit=sym in directive_hit,
            has_fresh_event=sym in event_pending,
            social_score=float(ie["social_score"]) if ie.get("social_score") is not None else None,
            social_fresh_hours=_hours_since(ie.get("last_enriched")),
            rvol=float(ie["rvol"]) if ie.get("rvol") is not None else None,
            avg_volume=float(ie["avg_volume"]) if ie.get("avg_volume") is not None else None,
            atr_pct=float(ie["atr_pct"]) if ie.get("atr_pct") is not None else None,
            outcome_hits=int(oc.get("hits", 0)),
            outcome_misses=int(oc.get("misses", 0)),
            outcome_neutral=int(oc.get("neutral", 0)),
            avg_realized_r=oc.get("avg_r"),
            research_actioned_rate=oc.get("actioned_rate"),
            sector=ie.get("sector") or meta.get("sector"),
        )
    return out