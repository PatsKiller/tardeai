"""paper_positions.py — monitored options position registry (PR1 lifecycle monitor).

Hybrid ingest: queue row + fill on open; broker sync on monitor runs.
Multi-broker fields (Alpaca first). Advisory only — never submits orders.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from lib.options_pipeline.card_semantics import execution_route_badge

Executor = Callable[..., Any]

STATUS_OPEN = "OPEN"
STATUS_CLOSED = "CLOSED"
STATUS_ERROR = "ERROR"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_executor() -> Executor:
    from db_adapter import _execute
    return _execute


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if x != x else x


def _proposal_json(row: dict) -> dict:
    pj = row.get("proposal_json")
    if isinstance(pj, str):
        try:
            pj = json.loads(pj)
        except (ValueError, TypeError):
            pj = {}
    return pj or {}


def underlying_from_occ(option_symbol: str | None) -> str:
    """Parse OCC root symbol, e.g. RTX260918C00160000 → RTX."""
    occ = str(option_symbol or "").strip().upper()
    if not occ:
        return ""
    m = re.match(r"^([A-Z]{1,6})", occ)
    return m.group(1) if m else ""


def _alpaca_meta(row: dict) -> dict:
    meta = row.get("meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (ValueError, TypeError):
            meta = {}
    return (meta or {}).get("alpaca_json") or {}


def _debit_credit(strategy: str, side: str | None = None) -> str:
    s = (strategy or "").lower()
    if s in ("covered_call", "cash_secured_put", "credit_spread",
             "put_credit_spread", "call_credit_spread"):
        return "credit"
    if (side or "").upper() == "SELL":
        return "credit"
    return "debit"


def load_open_positions(*, executor: Optional[Executor] = None,
                        broker: str | None = None,
                        limit: int = 100) -> list[dict]:
    ex = executor or _default_executor()
    if broker:
        rows = ex(
            """SELECT * FROM options_monitored_positions
               WHERE status = %s AND broker = %s
               ORDER BY opened_at DESC NULLS LAST LIMIT %s""",
            (STATUS_OPEN, broker, limit), fetch="all") or []
    else:
        rows = ex(
            """SELECT * FROM options_monitored_positions
               WHERE status = %s
               ORDER BY opened_at DESC NULLS LAST LIMIT %s""",
            (STATUS_OPEN, limit), fetch="all") or []
    return [dict(r) for r in rows]


def get_position_by_proposal(proposal_id: str, *, executor: Optional[Executor] = None) -> dict | None:
    ex = executor or _default_executor()
    row = ex(
        "SELECT * FROM options_monitored_positions WHERE proposal_id = %s",
        (proposal_id,), fetch="one")
    return dict(row) if row else None


def upsert_from_queue_fill(
    queue_row: dict,
    *,
    fill: dict,
    chain_quote: dict | None = None,
    executor: Optional[Executor] = None,
) -> dict:
    """Create or refresh OPEN position after Alpaca paper fill (hybrid ingest)."""
    ex = executor or _default_executor()
    pid = queue_row.get("proposal_id") or ""
    if not pid:
        return {"ok": False, "error": "proposal_id required"}
    pj = _proposal_json(queue_row)
    aj = _alpaca_meta(queue_row)
    route = execution_route_badge({**pj, **queue_row, "proposal_json": pj})
    if aj.get("request") or aj.get("response"):
        route = {"label": "Alpaca paper only", "kind": "tradeai_automated"}
    underlying = str(pj.get("underlying") or pj.get("symbol") or queue_row.get("symbol") or "")
    occ = str((aj.get("request") or {}).get("symbol") or pj.get("option_symbol") or "")
    fill_px = _f((fill or {}).get("price"))
    bid = _f((chain_quote or {}).get("bid"))
    ask = _f((chain_quote or {}).get("ask"))
    mid = _f((chain_quote or {}).get("mid")) or ((bid + ask) / 2.0 if bid and ask else fill_px)
    spread_pct = None
    if bid and ask and mid:
        spread_pct = round((ask - bid) / mid * 100.0, 2) if mid else None
    entry_dc = _debit_credit(str(pj.get("strategy") or queue_row.get("strategy") or ""),
                           pj.get("side"))
    meta = {
        "lane": "tradeai_automated",
        "queue_status": queue_row.get("status"),
        "discovery_ref": (pj.get("meta") or {}).get("discovery_ref"),
    }
    params = (
        pid, "alpaca", route["kind"],
        str((aj.get("response") or {}).get("id") or ""),
        occ,  # alpaca_position_id proxy = OCC until broker returns id
        pj.get("symbol") or queue_row.get("symbol"),
        underlying, occ,
        pj.get("strategy") or queue_row.get("strategy"),
        pj.get("side"), pj.get("option_type"),
        _f(pj.get("strike")) or None,
        pj.get("expiration"),
        int(pj.get("contracts") or 1),
        _f(pj.get("premium")) or None,
        fill_px or None,
        entry_dc,
        _f((chain_quote or {}).get("underlying_price") or pj.get("underlying_price")) or None,
        _f((chain_quote or {}).get("delta")) or None,
        _f((chain_quote or {}).get("gamma")) or None,
        _f((chain_quote or {}).get("theta")) or None,
        _f((chain_quote or {}).get("vega")) or None,
        _f((chain_quote or {}).get("iv")) or None,
        spread_pct,
        int(_f((chain_quote or {}).get("oi"))) if chain_quote else None,
        int(_f((chain_quote or {}).get("volume"))) if chain_quote else None,
        (fill or {}).get("filled_at") or _now_iso(),
        STATUS_OPEN, True, False,
        json.dumps(meta, default=str),
    )
    ex(
        """INSERT INTO options_monitored_positions (
            proposal_id, broker, execution_route, alpaca_order_id, alpaca_position_id,
            symbol, underlying_symbol, option_symbol, strategy, side, option_type,
            strike, expiration, contracts, entry_limit, entry_fill_price,
            entry_debit_credit, entry_underlying_price, entry_delta, entry_gamma,
            entry_theta, entry_vega, entry_iv, entry_spread_pct, entry_oi, entry_volume,
            opened_at, status, paper_only, live_eligible, meta_json
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s::jsonb
        )
        ON CONFLICT (proposal_id) DO UPDATE SET
            alpaca_order_id = EXCLUDED.alpaca_order_id,
            entry_fill_price = COALESCE(EXCLUDED.entry_fill_price, options_monitored_positions.entry_fill_price),
            entry_underlying_price = COALESCE(EXCLUDED.entry_underlying_price, options_monitored_positions.entry_underlying_price),
            entry_delta = COALESCE(EXCLUDED.entry_delta, options_monitored_positions.entry_delta),
            entry_gamma = COALESCE(EXCLUDED.entry_gamma, options_monitored_positions.entry_gamma),
            entry_theta = COALESCE(EXCLUDED.entry_theta, options_monitored_positions.entry_theta),
            entry_vega = COALESCE(EXCLUDED.entry_vega, options_monitored_positions.entry_vega),
            entry_iv = COALESCE(EXCLUDED.entry_iv, options_monitored_positions.entry_iv),
            entry_spread_pct = COALESCE(EXCLUDED.entry_spread_pct, options_monitored_positions.entry_spread_pct),
            status = CASE WHEN options_monitored_positions.status = 'CLOSED' THEN options_monitored_positions.status
                          ELSE EXCLUDED.status END,
            updated_at = NOW(),
            meta_json = options_monitored_positions.meta_json || EXCLUDED.meta_json""",
        params)
    pos = get_position_by_proposal(pid, executor=ex)
    return {"ok": True, "position_id": pos["id"] if pos else None, "proposal_id": pid}


def ensure_monitored_for_filled_queue_row(
    queue_row: dict,
    *,
    executor: Optional[Executor] = None,
) -> dict:
    """Idempotent backfill: ALPACA_PAPER_FILLED queue row → OPEN monitored position."""
    ex = executor or _default_executor()
    pid = queue_row.get("proposal_id") or ""
    if not pid:
        return {"ok": False, "error": "proposal_id required", "skipped": True}
    existing = get_position_by_proposal(pid, executor=ex)
    if existing and existing.get("status") in (STATUS_OPEN, STATUS_CLOSED):
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_registered",
            "position_id": existing.get("id"),
            "proposal_id": pid,
        }
    aj = _alpaca_meta(queue_row)
    fill = dict(aj.get("fill") or {})
    price = fill.get("price")
    if price is None and fill.get("net_debit") is not None:
        price = fill.get("net_debit")
    if price is None:
        resp = aj.get("response") or {}
        price = resp.get("filled_avg_price")
    if price is None and not fill:
        return {
            "ok": False,
            "error": "no fill blob in meta.alpaca_json",
            "skipped": True,
            "proposal_id": pid,
        }
    if "price" not in fill and price is not None:
        fill["price"] = float(price)
    return upsert_from_queue_fill(queue_row, fill=fill, executor=ex)


def mark_closed(
    proposal_id: str,
    *,
    reason: str = "broker_reconcile",
    executor: Optional[Executor] = None,
) -> dict:
    ex = executor or _default_executor()
    row = ex(
        """UPDATE options_monitored_positions
           SET status = %s, updated_at = NOW(),
               meta_json = meta_json || %s::jsonb
           WHERE proposal_id = %s AND status = %s
           RETURNING id""",
        (STATUS_CLOSED, json.dumps({"closed_reason": reason, "closed_at": _now_iso()}),
         proposal_id, STATUS_OPEN), fetch="one")
    return {"ok": bool(row), "changed": bool(row), "proposal_id": proposal_id,
            "position_id": row["id"] if row else None}


def upsert_orphan_error(
    *,
    option_symbol: str,
    broker: str,
    message: str,
    executor: Optional[Executor] = None,
    send_alert: bool = True,
) -> dict:
    """Broker position with no queue lineage → ERROR row for operator review."""
    ex = executor or _default_executor()
    occ = str(option_symbol or "").strip().upper()
    pid = f"orphan_{broker}_{occ}"
    existed = get_position_by_proposal(pid, executor=ex) is not None
    root = underlying_from_occ(occ)
    ex(
        """INSERT INTO options_monitored_positions (
            proposal_id, broker, symbol, underlying_symbol, option_symbol,
            status, paper_only, live_eligible, meta_json, opened_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,NOW())
        ON CONFLICT (proposal_id) DO UPDATE SET
            option_symbol = EXCLUDED.option_symbol,
            symbol = COALESCE(NULLIF(options_monitored_positions.symbol, ''), EXCLUDED.symbol),
            underlying_symbol = COALESCE(NULLIF(options_monitored_positions.underlying_symbol, ''), EXCLUDED.underlying_symbol),
            status = EXCLUDED.status,
            meta_json = options_monitored_positions.meta_json || EXCLUDED.meta_json,
            updated_at = NOW()""",
        (pid, broker, root or None, root or None, occ, STATUS_ERROR, True, False,
         json.dumps({"orphan": True, "message": message}, default=str)))
    pos = get_position_by_proposal(pid, executor=ex)
    if pos and send_alert and not existed:
        try:
            from lib.options_pipeline import paper_position_alerts as ppa
            from lib.options_pipeline.paper_position_monitor import load_config
            ppa.dispatch_lifecycle_alert(
                pos, alert_type=ppa.LIFECYCLE_ORPHAN, message=message,
                cfg=load_config(), executor=ex)
        except Exception:
            pass
    return {"ok": True, "proposal_id": pid, "status": STATUS_ERROR,
            "created": not existed}