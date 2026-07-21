"""paper_positions_api.py — PR3 API serializers for monitored + unified open options."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Callable, Optional

from lib.options_pipeline.card_semantics import (
    apply_card_semantics,
    execution_route_badge,
    safety_status_badge,
)

Executor = Callable[..., Any]

ADVICE_SEVERITY = {
    "CONSIDER_CLOSE_PAPER": "warn",
    "CONSIDER_ROLL_PAPER": "warn",
    "WATCH_PAPER": "warn",
    "DATA_STALE": "warn",
    "QUOTE_UNTRADABLE": "critical",
    "OUTCOME_READY": "info",
    "HOLD_PAPER": "positive",
}


def _default_executor() -> Executor:
    from db_adapter import _execute
    return _execute


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if x != x else x


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _parse_meta(v: Any) -> dict:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v) or {}
        except (ValueError, TypeError):
            return {}
    return {}


def _advice_to_lifecycle(advice: str | None) -> str:
    a = (advice or "").upper()
    if a in ("CONSIDER_CLOSE_PAPER", "OUTCOME_READY"):
        return "harvest"
    if a == "CONSIDER_ROLL_PAPER":
        return "monitor"
    if a in ("WATCH_PAPER", "DATA_STALE", "QUOTE_UNTRADABLE"):
        return "defend"
    return "let_mature"


def _advice_to_action(advice: str | None) -> str:
    a = (advice or "").upper()
    mapping = {
        "CONSIDER_CLOSE_PAPER": "Consider close (paper advisory)",
        "CONSIDER_ROLL_PAPER": "Consider roll (paper advisory)",
        "WATCH_PAPER": "Watch thresholds",
        "DATA_STALE": "Refresh chain quote",
        "QUOTE_UNTRADABLE": "Wide spread / no quote",
        "OUTCOME_READY": "Record outcome",
        "HOLD_PAPER": "Hold within thresholds",
    }
    return mapping.get(a, advice or "Monitor")


def enrich_position_semantics(card: dict[str, Any]) -> dict[str, Any]:
    """Apply desk card semantics to a position-shaped dict."""
    pseudo = {
        "strategy": card.get("strategy"),
        "side": card.get("side"),
        "option_type": card.get("option_type"),
        "broker": card.get("broker"),
        "paper_only": card.get("paper_only", True),
        "execution_route": card.get("execution_route"),
        "educational_paper_model": card.get("paper_only", True),
        "alpaca_paper_enabled": card.get("execution_route") == "tradeai_automated",
    }
    sem = apply_card_semantics(pseudo)
    card["execution_route_badge"] = sem.get("execution_route_badge")
    card["execution_route_kind"] = sem.get("execution_route_kind")
    card["execution_note"] = sem.get("execution_note")
    card["safety_status_badge"] = safety_status_badge(pseudo) or sem.get("safety_status_badge")
    card["is_paper_model_row"] = sem.get("is_paper_model_row", True)
    card["cashflow_label"] = sem.get("cashflow_label")
    card["cashflow_is_credit"] = sem.get("cashflow_is_credit")
    return card


def serialize_monitored_row(row: dict, snap: dict | None = None) -> dict[str, Any]:
    """Map DB position + optional latest snapshot to API card."""
    meta = _parse_meta(row.get("meta_json"))
    snap = snap or {}
    advice = snap.get("advice_label") or meta.get("advice_label")
    out: dict[str, Any] = {
        "id": f"mon-{row.get('id')}",
        "position_id": row.get("id"),
        "proposal_id": row.get("proposal_id"),
        "position_source": "monitored",
        "broker": row.get("broker"),
        "execution_route": row.get("execution_route"),
        "status": row.get("status"),
        "paper_only": bool(row.get("paper_only", True)),
        "live_eligible": bool(row.get("live_eligible", False)),
        "underlying": row.get("underlying_symbol") or row.get("symbol"),
        "symbol": row.get("underlying_symbol") or row.get("symbol"),
        "occ_symbol": row.get("option_symbol"),
        "strategy": row.get("strategy"),
        "side": (row.get("side") or "").lower(),
        "option_type": row.get("option_type"),
        "strike": _f(row.get("strike")) or None,
        "expiration": _iso(row.get("expiration")),
        "contracts": int(row.get("contracts") or 1),
        "qty": int(row.get("contracts") or 1),
        "entry_fill_price": _f(row.get("entry_fill_price")) or None,
        "avg_entry": _f(row.get("entry_fill_price")) or None,
        "entry_debit_credit": row.get("entry_debit_credit"),
        "opened_at": _iso(row.get("opened_at")),
        "advice_label": advice,
        "advice_reason": snap.get("advice_reason"),
        "recommended_action": _advice_to_action(advice),
        "rationale": snap.get("advice_reason") or meta.get("message"),
        "lifecycle_phase": _advice_to_lifecycle(advice),
        "severity": ADVICE_SEVERITY.get(str(advice or "").upper(), "info"),
        "still_working": str(advice or "").upper() in ("HOLD_PAPER", "WATCH_PAPER"),
        "mark": _f(snap.get("option_mark") or snap.get("option_mid")) or None,
        "underlying_price": _f(snap.get("underlying_price")) or None,
        "unrealized_pnl": _f(snap.get("unrealized_pnl")) if snap else None,
        "unrealized_pnl_pct": _f(snap.get("unrealized_pnl_pct")) if snap else None,
        "dte": snap.get("dte"),
        "delta": _f(snap.get("delta")) or None,
        "theta": _f(snap.get("theta")) or None,
        "vega": _f(snap.get("vega")) or None,
        "iv": _f(snap.get("iv")) or None,
        "spread_pct": _f(snap.get("spread_pct")) if snap.get("spread_pct") is not None else None,
        "mfe": _f(snap.get("max_favorable_excursion")) if snap else None,
        "mae": _f(snap.get("max_adverse_excursion")) if snap else None,
        "quote_source": snap.get("quote_source"),
        "snapshot_at": _iso(snap.get("snapshot_at")),
        "risk_flags": (
            json.loads(snap["risk_flags_json"]) if isinstance(snap.get("risk_flags_json"), str)
            else (snap.get("risk_flags_json") or [])
        ) if snap else [],
        "meta": meta,
        "action_buttons": [
            {"action": "review_chain", "label": "View Chain"},
            {"action": "review_paper_guards", "label": "Review Paper Guards"},
        ],
    }
    route = execution_route_badge({
        "broker": out["broker"],
        "paper_only": out["paper_only"],
        "execution_route": out["execution_route"],
        "educational_paper_model": out["paper_only"],
        "alpaca_paper_enabled": out["execution_route"] == "tradeai_automated",
    })
    out["route_badge"] = route
    return enrich_position_semantics(out)


def _latest_snapshot(position_id: int, executor: Executor) -> dict:
    row = executor(
        """SELECT * FROM options_monitored_position_snapshots
           WHERE position_id = %s ORDER BY snapshot_at DESC LIMIT 1""",
        (position_id,), fetch="one")
    return dict(row) if row else {}


def list_monitored_positions(
    *,
    status: str = "OPEN",
    broker: str | None = None,
    symbol: str | None = None,
    limit: int = 100,
    executor: Optional[Executor] = None,
) -> list[dict]:
    ex = executor or _default_executor()
    clauses = ["status = %s"]
    params: list[Any] = [status]
    if broker:
        clauses.append("broker = %s")
        params.append(broker)
    if symbol:
        clauses.append("UPPER(underlying_symbol) = %s")
        params.append(symbol.upper())
    params.append(limit)
    sql = f"""SELECT * FROM options_monitored_positions
              WHERE {' AND '.join(clauses)}
              ORDER BY opened_at DESC NULLS LAST LIMIT %s"""
    rows = ex(sql, tuple(params), fetch="all") or []
    return [serialize_monitored_row(dict(r), _latest_snapshot(int(r["id"]), ex)) for r in rows]


def get_monitored_position(position_id: int, *, executor: Optional[Executor] = None) -> dict | None:
    ex = executor or _default_executor()
    row = ex("SELECT * FROM options_monitored_positions WHERE id = %s",
             (position_id,), fetch="one")
    if not row:
        return None
    return serialize_monitored_row(dict(row), _latest_snapshot(position_id, ex))


def list_position_alerts(
    *,
    unacked_only: bool = True,
    limit: int = 50,
    executor: Optional[Executor] = None,
) -> list[dict]:
    ex = executor or _default_executor()
    if unacked_only:
        rows = ex(
            """SELECT a.*, p.underlying_symbol, p.proposal_id, p.execution_route, p.strategy
               FROM options_monitored_alerts a
               JOIN options_monitored_positions p ON p.id = a.position_id
               WHERE a.acknowledged_at IS NULL
               ORDER BY a.created_at DESC LIMIT %s""",
            (limit,), fetch="all") or []
    else:
        rows = ex(
            """SELECT a.*, p.underlying_symbol, p.proposal_id, p.execution_route, p.strategy
               FROM options_monitored_alerts a
               JOIN options_monitored_positions p ON p.id = a.position_id
               ORDER BY a.created_at DESC LIMIT %s""",
            (limit,), fetch="all") or []
    out = []
    for r in rows:
        d = dict(r)
        out.append({
            "id": d.get("id"),
            "position_id": d.get("position_id"),
            "proposal_id": d.get("proposal_id"),
            "underlying": d.get("underlying_symbol"),
            "strategy": d.get("strategy"),
            "execution_route": d.get("execution_route"),
            "alert_type": d.get("alert_type"),
            "severity": d.get("severity"),
            "message": d.get("message"),
            "action": _advice_to_action(str(d.get("alert_type") or "").upper()),
            "created_at": _iso(d.get("created_at")),
            "acknowledged_at": _iso(d.get("acknowledged_at")),
            "meta": _parse_meta(d.get("meta_json")),
        })
    return out


def acknowledge_alert(alert_id: int, *, executor: Optional[Executor] = None) -> dict:
    ex = executor or _default_executor()
    res = ex(
        """UPDATE options_monitored_alerts
           SET acknowledged_at = NOW(),
               meta_json = meta_json || %s::jsonb
           WHERE id = %s AND acknowledged_at IS NULL""",
        (json.dumps({"ack_source": "ui"}), alert_id))
    return {"ok": bool(res), "alert_id": alert_id}


def position_filter_facets(positions: list[dict]) -> dict:
    facets: dict[str, Any] = {
        "total": len(positions),
        "by_source": {},
        "by_route": {},
        "by_broker": {},
        "by_option_type": {},
        "by_side": {},
        "needs_action": 0,
        "paper_only": 0,
    }
    for p in positions:
        src = p.get("position_source") or "unknown"
        facets["by_source"][src] = facets["by_source"].get(src, 0) + 1
        route = p.get("execution_route_kind") or p.get("execution_route") or "unknown"
        facets["by_route"][route] = facets["by_route"].get(route, 0) + 1
        br = p.get("broker") or "unknown"
        facets["by_broker"][br] = facets["by_broker"].get(br, 0) + 1
        ot = p.get("option_type") or "unknown"
        facets["by_option_type"][ot] = facets["by_option_type"].get(ot, 0) + 1
        sd = p.get("side") or "unknown"
        facets["by_side"][sd] = facets["by_side"].get(sd, 0) + 1
        if p.get("still_working") is False or str(p.get("severity") or "").lower() in ("warn", "critical"):
            facets["needs_action"] += 1
        if p.get("paper_only") or p.get("is_paper_model_row"):
            facets["paper_only"] += 1
    return facets


def filter_positions(
    positions: list[dict],
    *,
    symbol: str = "",
    option_type: str = "",
    side: str = "",
    route: str = "",
    source: str = "",
    paper_only: bool | None = None,
) -> list[dict]:
    out = positions
    if symbol:
        out = [p for p in out if str(p.get("underlying") or "").upper() == symbol.upper()]
    if option_type:
        out = [p for p in out if str(p.get("option_type") or "").lower() == option_type.lower()]
    if side:
        out = [p for p in out if str(p.get("side") or "").lower() == side.lower()]
    if route:
        out = [p for p in out if str(p.get("execution_route_kind") or p.get("execution_route") or "") == route]
    if source:
        out = [p for p in out if str(p.get("position_source") or "") == source]
    if paper_only is True:
        out = [p for p in out if p.get("paper_only") or p.get("is_paper_model_row")]
    return out


def build_unified_open_positions(
    broker_positions: list[dict],
    monitored_positions: list[dict],
) -> list[dict]:
    """Merge Schwab broker legs + monitored registry (dedupe by OCC when possible)."""
    seen_occ: set[str] = set()
    unified: list[dict] = []
    for p in broker_positions:
        occ = str(p.get("occ_symbol") or "").upper()
        card = dict(p)
        card["position_source"] = "broker"
        card["unified_id"] = f"broker:{card.get('id')}"
        if not card.get("execution_route_kind"):
            card["execution_route_kind"] = "schwab_live" if p.get("account_key", "").startswith("schwab") else "review_only"
            card["execution_route_badge"] = "Schwab live path · 2FA required" if card["execution_route_kind"] == "schwab_live" else "Review only"
        unified.append(card)
        if occ:
            seen_occ.add(occ)
    for m in monitored_positions:
        occ = str(m.get("occ_symbol") or "").upper()
        if occ and occ in seen_occ:
            continue
        card = dict(m)
        card["unified_id"] = f"monitored:{card.get('position_id')}"
        unified.append(card)
    return unified