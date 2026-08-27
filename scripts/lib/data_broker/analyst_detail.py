"""Analyst Detail — Data Broker read model for Yahoo target price consensus.

Batch-reads yahoo_analyst_targets_history (canonical store for target mean/low/high,
recommendation_key, analyst count). Normalized for entry planner consumers.
"""
from __future__ import annotations

from typing import Any


def get_analyst_targets(db_query, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Return {SYMBOL: {target_mean, target_low, target_high, recommendation_key, analyst_count}}
    for a batch, taking only the latest row per symbol.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") injected by the caller.
        symbols: list of upper-case symbols.
    """
    symbols = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {}
    rows = db_query(
        """SELECT DISTINCT ON (upper(symbol))
                  upper(symbol) AS symbol, target_mean_price, target_high_price, target_low_price,
                  recommendation_key, number_of_analyst_opinions, created_at
           FROM yahoo_analyst_targets_history
           WHERE upper(symbol) = ANY(%s)
           ORDER BY upper(symbol), created_at DESC NULLS LAST""",
        (symbols,),
    ) or []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            out[sym] = {
                "target_mean": row.get("target_mean_price"),
                "target_high": row.get("target_high_price"),
                "target_low": row.get("target_low_price"),
                "recommendation_key": row.get("recommendation_key"),
                "analyst_count": row.get("number_of_analyst_opinions"),
                "created_at": row.get("created_at"),
            }
    return out


def _db_query(sql, params=None, fetch="all"):
    """Injected-callable shape the module's functions expect."""
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn:
            return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        if fetch == "one":
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None
        rows = cur.fetchall()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def get_analyst_detail(days: int = 30) -> dict[str, Any]:
    """Domain collector the CIO snapshot resolves by this exact name.

    `cio_financial_snapshot._EXTERNAL_ADAPTER_FUNCTIONS` maps the
    `analyst_actions` domain to `get_analyst_detail`, and that name did not
    exist -- the module exposed only `get_analyst_targets(db_query, symbols)`,
    which needs arguments the snapshot never passes. So `getattr` returned None,
    no collector was registered, and the domain reported DATA_UNAVAILABLE while
    9,818 rows sat in `yahoo_analyst_targets_history`.

    Summarises recent analyst target activity rather than one symbol, because
    the domain answers "what have analysts done lately", not "what about X".

    `as_of` is the newest row's timestamp, never `now()`: stamping the read time
    would report the domain fresh on a feed that had stopped updating.
    """
    rows = _db_query(
        """SELECT upper(symbol) AS symbol, target_mean_price, recommendation_key,
                  number_of_analyst_opinions, created_at
           FROM yahoo_analyst_targets_history
           WHERE created_at > now() - make_interval(days => %s)
           ORDER BY created_at DESC
           LIMIT 500""",
        (int(days),),
    ) or []

    if not rows:
        return {"state": "DATA_UNAVAILABLE", "as_of": "", "actions": [],
                "gap_reason": "no_analyst_target_rows_in_window"}

    newest = max((r.get("created_at") for r in rows if r.get("created_at")), default=None)
    return {
        "state": "AVAILABLE",
        "as_of": newest.isoformat() if newest else "",
        "action_count": len(rows),
        "symbols_covered": sorted({str(r.get("symbol")) for r in rows if r.get("symbol")}),
        "actions": [
            {"symbol": str(r.get("symbol")) if r.get("symbol") else None,
             "target_mean": float(r["target_mean_price"]) if r.get("target_mean_price") is not None else None,
             "recommendation": r.get("recommendation_key"),
             "analyst_count": int(r["number_of_analyst_opinions"]) if r.get("number_of_analyst_opinions") is not None else None,
             "at": r["created_at"].isoformat() if r.get("created_at") else None}
            for r in rows[:100]
        ],
    }
