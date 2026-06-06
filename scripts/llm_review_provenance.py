#!/usr/bin/env python3
"""llm_review_provenance.py — EXACT lineage resolver for trade_llm_reviews rows. No fuzzy mutation.

Resolution priority (exact only):
  1. backtest_trade_id -> strategy_backtest_trades.id  (simulation review: strategy_id, account; no trade_instance)
  2. paper_trade_id -> trade_instances(source_table='paper_trades', source_trade_id)
  3. trade_instance_id already present -> fill strategy/account/source from trade_instances
  4. structured eval with input_snapshot(symbol,open_date,close_date) -> trade_backtest_results 1:1 -> trade_instance
Returns a provenance dict + confidence + notes. Used by the backfill + by the review writer at insert time.
"""

PROV_COLS = ("trade_instance_id", "strategy_id", "account", "source_system", "source_table",
             "source_trade_id", "execution_broker", "execution_environment", "provenance_kind",
             "provenance_confidence", "provenance_notes")


def _ti_fields(cur, ti_id):
    cur.execute("SELECT strategy_id, execution_account, execution_broker, execution_environment, source_system, source_table, source_trade_id FROM trade_instances WHERE id=%s", (ti_id,))
    r = cur.fetchone()
    if not r:
        return {}
    return {"strategy_id": r[0], "account": r[1], "execution_broker": r[2], "execution_environment": r[3],
            "source_system": r[4], "source_table": r[5], "source_trade_id": r[6]}


def resolve_review_provenance(conn, *, backtest_trade_id=None, paper_trade_id=None, trade_instance_id=None,
                              symbol=None, open_date=None, close_date=None, source_table=None):
    """Exact lineage resolver. Returns {fields..., provenance_kind, provenance_confidence, provenance_notes}."""
    cur = conn.cursor()
    out = {"provenance_kind": "unknown", "provenance_confidence": "unlinked_imported_or_simulation",
           "provenance_notes": ""}

    # 1. simulation review -> strategy_backtest_trades (has strategy_id + account; sim, no trade_instance)
    if backtest_trade_id is not None and (source_table in (None, "strategy_backtest_trades")):
        cur.execute("SELECT strategy_id, account FROM strategy_backtest_trades WHERE id=%s", (backtest_trade_id,))
        r = cur.fetchone()
        if r:
            out.update({"strategy_id": r[0], "account": r[1], "source_system": "simulation",
                        "source_table": "strategy_backtest_trades", "source_trade_id": str(backtest_trade_id),
                        "provenance_kind": "simulation", "provenance_confidence": "exact_backtest_trade",
                        "provenance_notes": "exact sbt.id join"})
            return out

    # 2. paper review -> trade_instance via paper_trade_id
    if paper_trade_id is not None and not trade_instance_id:
        cur.execute("SELECT id FROM trade_instances WHERE source_table='paper_trades' AND source_trade_id=%s", (str(paper_trade_id),))
        r = cur.fetchone()
        if r:
            trade_instance_id = r[0]
            out.update({"provenance_kind": "paper", "provenance_confidence": "exact_paper_trade",
                        "provenance_notes": "exact paper_trade_id->trade_instance"})

    # 4. structured eval -> trade_backtest_results by exact (symbol, open_date, close_date) 1:1 -> trade_instance
    if not trade_instance_id and symbol and open_date and close_date:
        cur.execute("""SELECT id, trade_instance_id FROM trade_backtest_results
                       WHERE symbol=%s AND open_date::date=%s::date AND close_date::date=%s::date""",
                    (symbol, open_date, close_date))
        rows = cur.fetchall()
        if len(rows) == 1:
            out["backtest_result_id"] = rows[0][0]
            if rows[0][1]:
                trade_instance_id = rows[0][1]
                out.update({"provenance_kind": "imported_backtest", "provenance_confidence": "exact_trade_instance",
                            "provenance_notes": "exact (symbol,open,close)->tbr->trade_instance"})
            else:
                out.update({"provenance_kind": "imported_backtest", "provenance_confidence": "exact_backtest_row_no_instance",
                            "provenance_notes": "exact tbr match but tbr has no trade_instance_id"})

    # 3. fill from trade_instance if we have one
    if trade_instance_id:
        out["trade_instance_id"] = trade_instance_id
        for k, v in _ti_fields(cur, trade_instance_id).items():
            out.setdefault(k, v) if out.get(k) is None else None
            if out.get(k) is None:
                out[k] = v
        if out["provenance_kind"] == "unknown":
            out.update({"provenance_kind": "paper" if out.get("source_table") == "paper_trades" else "imported_backtest",
                        "provenance_confidence": "exact_trade_instance"})
    return out


if __name__ == "__main__":
    import os, psycopg2, json, sys
    conn = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                            user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
    print(json.dumps(resolve_review_provenance(conn, backtest_trade_id=int(sys.argv[1])) if len(sys.argv) > 1 else {}, default=str, indent=2))
