#!/usr/bin/env python3
"""options_execution_friction.py — v1.2.3 P1-2: execution-friction evidence.

Writes ONE row per lifecycle execution from REAL ticket + fill evidence.
Nothing historical is fabricated; unknown values stay NULL; manual estimates
can never be labeled ACTUAL (data_quality_state guards the label)."""
from __future__ import annotations

import json
from datetime import datetime, timezone


def ensure_friction_tables(cur, conn):
    cur.execute("""CREATE TABLE IF NOT EXISTS options_execution_friction (
        friction_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL,
        ticket_id int NOT NULL,
        occ_symbol text NOT NULL,
        instruction text NOT NULL,
        decision_quote_at timestamptz,
        approval_quote_at timestamptz,
        armed_quote_at timestamptz,
        submitted_limit numeric,
        bid_at_decision numeric, ask_at_decision numeric, mid_at_decision numeric,
        fill_price numeric,
        slippage_vs_mid numeric,          -- direction-aware: + = paid worse than mid
        slippage_vs_limit numeric,
        spread_at_decision numeric,
        spread_at_execution numeric,
        order_age_seconds numeric,
        partial_fill_count int,
        time_to_first_fill_seconds numeric,
        time_to_complete_seconds numeric,
        execution_source text NOT NULL,
        quote_provenance text,
        data_quality_state text NOT NULL,  -- ACTUAL | ESTIMATED | UNAVAILABLE
        created_at timestamptz DEFAULT now())""")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_friction_ticket_leg
        ON options_execution_friction (ticket_id, occ_symbol, instruction)""")
    conn.commit()


def _dir_slip(instruction: str, fill: float, ref: float) -> float:
    """Positive = worse than reference for the desk (paid more on buys,
    received less on sells)."""
    buy = instruction in ("BTC", "BTO")
    return round((fill - ref) if buy else (ref - fill), 6)


def record_friction(cur, conn, ticket: dict, ticket_id: int, cum: dict,
                    source: str, manage_txn: bool = True) -> int:
    """Called from fill-evidence application with the ticket json + cumulative
    per-leg fills. ACTUAL only when both quotes and fills are real.
    manage_txn=False → caller owns the transaction (NO ensure DDL, NO commit) —
    required when invoked inside the atomic evidence transaction."""
    if manage_txn:
        ensure_friction_tables(cur, conn)
    n = 0
    armed_at = ticket.get("quote_ts")
    # sanity: unparseable timestamps stay NULL rather than poisoning the txn
    try:
        if armed_at:
            datetime.fromisoformat(str(armed_at).replace("Z", "+00:00"))
    except Exception:
        armed_at = None
    for t in ticket.get("legs", []):
        occ = (t.get("occ_symbol") or t.get("occ_target") or "").strip()
        c = cum.get((occ, t["instruction"]))
        if not c:
            continue
        bid, ask = t.get("bid"), t.get("ask")
        mid = (bid + ask) / 2 if bid is not None and ask is not None else None
        fill = c["vwap"]
        quality = "ACTUAL" if (mid is not None and source != "operator_manual") else (
            "ESTIMATED" if mid is not None else "UNAVAILABLE")
        first_t = min((f.get("t") or f.get("executed_at") for f in c.get("raw", [])),
                      default=None) if c.get("raw") else None
        cur.execute("""INSERT INTO options_execution_friction
            (strategy_position_id, ticket_id, occ_symbol, instruction,
             armed_quote_at, submitted_limit, bid_at_decision, ask_at_decision,
             mid_at_decision, fill_price, slippage_vs_mid, slippage_vs_limit,
             spread_at_decision, partial_fill_count, execution_source,
             quote_provenance, data_quality_state)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (ticket_id, occ_symbol, instruction) DO UPDATE SET
              fill_price=EXCLUDED.fill_price, slippage_vs_mid=EXCLUDED.slippage_vs_mid,
              slippage_vs_limit=EXCLUDED.slippage_vs_limit,
              partial_fill_count=EXCLUDED.partial_fill_count,
              data_quality_state=EXCLUDED.data_quality_state""",
            (ticket["strategy_position_id"], ticket_id, occ, t["instruction"],
             armed_at, t.get("proposed_limit"), bid, ask, mid, fill,
             _dir_slip(t["instruction"], fill, mid) if mid is not None else None,
             _dir_slip(t["instruction"], fill, float(t["proposed_limit"]))
             if t.get("proposed_limit") is not None else None,
             round(ask - bid, 6) if bid is not None and ask is not None else None,
             c.get("fills_count"), source,
             f"ticket:{ticket_id} quotes@{armed_at}", quality))
        n += cur.rowcount
    if manage_txn:
        conn.commit()
    return n


def friction_summary(cur, query=None) -> dict:
    cur.execute("""SELECT data_quality_state, count(*), avg(slippage_vs_mid),
                          avg(spread_at_decision)
                   FROM options_execution_friction GROUP BY 1""")
    return {"by_quality": [{"state": r[0], "n": r[1],
                            "avg_slippage_vs_mid": float(r[2]) if r[2] is not None else None,
                            "avg_spread": float(r[3]) if r[3] is not None else None}
                           for r in cur.fetchall()],
            "labels": {"ACTUAL": "real quotes + real fills", "ESTIMATED": "manual/derived",
                       "UNAVAILABLE": "quotes unknown — NULLs preserved"}}
