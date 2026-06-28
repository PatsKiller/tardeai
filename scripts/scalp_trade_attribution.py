#!/usr/bin/env python3
"""scalp_trade_attribution.py — true, conservative attribution of momentum_scalp paper trades.

Operator correction (2026-06-28): prior reports over-attributed momentum_scalp paper trades
(e.g. "17 opened / 3 closed"). Those figures counted non-executed rows (cancelled / dedup) as
trades and an unlinked direct-label row as confirmed. This module is the single, conservative
source of truth used by the funnel report and the validation tracker.

A paper_trades row counts as a CONFIRMED momentum_scalp trade only when ALL hold:
  * paper_trades.strategy_id = 'momentum_scalp'  (priority-1 attribution), AND
  * status is an EXECUTED status (the trade actually entered — not cancelled/dedup/rejected/pending),
    AND
  * lineage or fill evidence: the linked proposal's strategy_id is also 'momentum_scalp', OR a real
    broker fill exists (broker_order_id present / broker_status filled).

Rows that are direct-labelled but lack lineage AND fill evidence are AMBIGUOUS (reported under
unknown, never counted as confirmed). Rows whose linked proposal is a DIFFERENT strategy are
MISMATCHED (mis-attribution, reported, never counted). Non-executed rows are not trades.

Read-only. No writes, no broker calls. Missing columns degrade to a `missing_columns` WARN.
"""
from __future__ import annotations

STRATEGY = "momentum_scalp"
# Statuses meaning the trade actually entered the market (paper). Everything else (cancelled,
# dedup_removed, rejected, pending, expired, duplicate, ...) is NOT an executed trade.
EXECUTED_STATUSES = ("closed", "open", "monitoring", "filled", "partially_filled")
CLOSED_STATUSES = ("closed",)


def classify(strategy_id, prop_strategy, status, broker_order_id=None, broker_status=None) -> str:
    """Pure, deterministic classification of one paper_trades row (no DB).

    Returns: 'confirmed' | 'proposal_only' | 'ambiguous' | 'mismatched' | 'non_executed' | 'not_scalp'.
    Only 'confirmed' (and the conservative 'proposal_only') count toward the validation sample.
    """
    direct = (strategy_id == STRATEGY)
    prop_match = (prop_strategy == STRATEGY)
    if not direct and not prop_match:
        return "not_scalp"
    if direct and prop_strategy is not None and prop_strategy != STRATEGY:
        return "mismatched"
    if status not in EXECUTED_STATUSES:
        return "non_executed"
    fill_evidence = bool(broker_order_id) or (broker_status in ("filled", "partially_filled"))
    if direct and (prop_match or fill_evidence):
        return "confirmed"
    if (not direct) and prop_match:
        return "proposal_only"
    return "ambiguous"


def _has_columns(conn, table, cols):
    try:
        cur = conn.cursor()
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table,))
        have = {r[0] for r in cur.fetchall()}
        return have, [c for c in cols if c not in have]
    except Exception:
        return set(), list(cols)


def attribute(conn, days: int | None = None) -> dict:
    """Return the conservative momentum_scalp paper-trade attribution breakdown."""
    needed = ["id", "symbol", "strategy_id", "status", "pnl", "proposal_id",
              "broker_order_id", "broker_status", "entry_time", "discovery_trace_id"]
    have, missing = _has_columns(conn, "paper_trades", needed)
    if "strategy_id" in missing or "status" in missing:
        return {"ok": False, "status": "WARN",
                "missing_columns": missing,
                "note": "paper_trades lacks strategy_id/status — cannot attribute; reporting UNKNOWN."}

    def col(name, default="NULL"):
        return f"pt.{name}" if name in have else default

    where_time = ""
    params = []
    if days is not None and "entry_time" in have:
        where_time = "AND pt.entry_time > NOW() - INTERVAL %s"
        params = [f"{int(days)} days"]

    sql = f"""
        SELECT pt.id, {col('symbol')} AS symbol, pt.strategy_id, pt.status, {col('pnl', '0')} AS pnl,
               {col('proposal_id')} AS proposal_id, ptp.strategy_id AS prop_strategy,
               {col('broker_order_id')} AS broker_order_id, {col('broker_status')} AS broker_status,
               {col('discovery_trace_id')} AS discovery_trace_id
        FROM paper_trades pt
        LEFT JOIN paper_trade_proposals ptp ON ptp.id = {col('proposal_id')}
        WHERE (pt.strategy_id = %s OR ptp.strategy_id = %s)
        {where_time}
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, [STRATEGY, STRATEGY] + params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "status": "WARN", "missing_columns": missing,
                "note": f"query failed: {str(e).splitlines()[0][:120]}"}

    buckets = {"confirmed": [], "proposal_only": [], "ambiguous": [],
               "mismatched": [], "non_executed": [], "not_scalp": []}
    for r in rows:
        prop_strat = r.get("prop_strategy")
        cat = classify(r.get("strategy_id"), prop_strat, r.get("status"),
                       r.get("broker_order_id"), r.get("broker_status"))
        chain = {
            "trade_id": r["id"], "symbol": r.get("symbol"), "status": r.get("status"),
            "pnl": float(r["pnl"]) if r.get("pnl") is not None else None,
            "pt_strategy_id": r.get("strategy_id"), "proposal_id": r.get("proposal_id"),
            "proposal_strategy_id": prop_strat, "broker_order_id": r.get("broker_order_id"),
            "broker_status": r.get("broker_status"), "discovery_trace_id": r.get("discovery_trace_id"),
            "closed": r.get("status") in CLOSED_STATUSES, "category": cat,
        }
        buckets[cat].append(chain)
    confirmed = buckets["confirmed"] + buckets["proposal_only"]
    ambiguous = buckets["ambiguous"]
    mismatched = buckets["mismatched"]
    non_executed = buckets["non_executed"]
    proposal_only = buckets["proposal_only"]

    confirmed_closed = [c for c in confirmed if c["closed"]]
    winners = [c for c in confirmed_closed if (c["pnl"] or 0) > 0]
    gw = sum(c["pnl"] for c in confirmed_closed if (c["pnl"] or 0) > 0)
    gl = sum(c["pnl"] for c in confirmed_closed if (c["pnl"] or 0) < 0)

    return {
        "ok": True,
        "status": "PASS" if not missing else "WARN",
        "strategy": STRATEGY,
        "window_days": days,
        "operator_correction": "no confirmed momentum_scalp paper trades per operator; "
                               "any count below is what the DB proves with correct attribution",
        "confirmed_opened": len(confirmed),
        "confirmed_closed": len(confirmed_closed),
        "confirmed_winners": len(winners),
        "confirmed_win_rate": round(len(winners) / len(confirmed_closed), 4) if confirmed_closed else None,
        "confirmed_profit_factor": round(gw / abs(gl), 4) if gl else None,
        "ambiguous_count": len(ambiguous),
        "mismatched_count": len(mismatched),
        "proposal_only_count": len(proposal_only),
        "non_executed_count": len(non_executed),
        "unknown_strategy_paper_trades": len(ambiguous) + len(mismatched),
        "confirmed_trade_ids": [c["trade_id"] for c in confirmed],
        "ambiguous_trade_ids": [c["trade_id"] for c in ambiguous],
        "attribution_chains": confirmed,
        "ambiguous_chains": ambiguous,
        "mismatched_chains": mismatched,
        "missing_columns": missing,
        "executed_statuses": list(EXECUTED_STATUSES),
        "note": "Conservative attribution: non-executed rows are not trades; direct-label rows "
                "without lineage/fill are ambiguous (unknown), not momentum_scalp.",
    }


if __name__ == "__main__":
    import json
    from db_adapter import get_connection
    print(json.dumps(attribute(get_connection()), indent=2, default=str))
