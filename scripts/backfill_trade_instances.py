#!/usr/bin/env python3
"""backfill_trade_instances.py — populate trade_instances + link consumer tables (additive).

Sources: paper_trades (alpaca_paper, rich lineage) + trades non-alpaca (schwab/fidelity imports).
Then stamp trade_instance_id on hermes/journal/backtest/edge/efficacy/outcome-chain via exact source keys,
and populate canonical trade_edge_comparison from paper_trade_edge_comparison. No fabrication.

  python3 scripts/backfill_trade_instances.py            # dry-run (counts only)
  python3 scripts/backfill_trade_instances.py --apply
"""
import os, sys, json, psycopg2, psycopg2.extras

INS_PAPER = """
INSERT INTO trade_instances (trade_uid, source_system, source_table, source_trade_id,
  execution_broker, execution_account, execution_environment, trade_mode,
  symbol, strategy_id, signal_id, source_signal_id, strategy_card_id, candidate_id, proposal_id,
  status, side, shares, entry_price, entry_time, exit_price, exit_time, pnl, pnl_pct, r_multiple, hold_time_min,
  trade_key, lineage_confidence, lineage_source)
SELECT 'paper_trades:'||id, 'tradeai_automated', 'paper_trades', id::text,
  COALESCE(execution_broker,'alpaca'), COALESCE(execution_account, account, 'tradeai_automated'),
  COALESCE(execution_environment,'paper'), 'paper',
  symbol, strategy_id, signal_id, source_signal_id, source_strategy_card_id, candidate_id, proposal_id::text,
  COALESCE(status, CASE WHEN exit_time IS NOT NULL THEN 'closed' END), 'long', shares,
  entry_price, entry_time, exit_price, exit_time, pnl, pnl_pct, r_multiple, hold_time_min,
  trade_key, COALESCE(lineage_confidence, CASE WHEN proposal_id IS NOT NULL THEN 'exact' ELSE 'missing' END),
  COALESCE(lineage_source,'paper_trades')
FROM paper_trades
ON CONFLICT (source_table, source_trade_id) DO UPDATE SET
  status=EXCLUDED.status, exit_price=EXCLUDED.exit_price, exit_time=EXCLUDED.exit_time,
  pnl=EXCLUDED.pnl, pnl_pct=EXCLUDED.pnl_pct, r_multiple=EXCLUDED.r_multiple,
  signal_id=EXCLUDED.signal_id, trade_key=EXCLUDED.trade_key, updated_at=now();
"""

INS_TRADES = """
INSERT INTO trade_instances (trade_uid, source_system, source_table, source_trade_id,
  execution_broker, execution_account, execution_environment, trade_mode,
  symbol, strategy_id, status, side, shares, entry_price, entry_time, exit_price, exit_time,
  pnl, pnl_pct, r_multiple, hold_time_min, trade_key, lineage_confidence, lineage_source)
SELECT 'trades:'||trade_id,
  CASE WHEN account ILIKE 'schwab%' THEN 'schwab_import'
       WHEN account ILIKE 'fidelity%' THEN 'fidelity_import'
       ELSE COALESCE(broker,'import')||'_import' END,
  'trades', trade_id::text,
  broker, account, CASE WHEN account ILIKE '%paper%' THEN 'paper' ELSE 'live' END, 'import',
  symbol, strategy_id, status, 'long', shares, entry_price, entry_date::timestamptz, exit_price, exit_date::timestamptz,
  pnl, pnl_pct, r_multiple, hold_time_min,
  CASE WHEN exit_date IS NOT NULL THEN symbol||':'||account||':'||exit_date::date::text END,
  'imported_broker_statement', 'trades'
FROM trades WHERE account NOT ILIKE 'alpaca%'
ON CONFLICT (source_table, source_trade_id) DO UPDATE SET
  status=EXCLUDED.status, exit_price=EXCLUDED.exit_price, exit_time=EXCLUDED.exit_time,
  pnl=EXCLUDED.pnl, pnl_pct=EXCLUDED.pnl_pct, r_multiple=EXCLUDED.r_multiple, updated_at=now();
"""

# (table, link_column, instance_source_table) — exact-key links to paper instances
PAPER_LINKS = [("journal_trade_reviews", "paper_trade_id"), ("trade_backtest_results", "paper_trade_id"),
               ("paper_trade_edge_comparison", "paper_trade_id"), ("candidate_shadow_efficacy", "paper_trade_id"),
               ("proposal_outcome_chain", "paper_trade_id")]


def main():
    apply = "--apply" in sys.argv
    c = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                         user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if apply:
        cur.execute(INS_PAPER)
        cur.execute(INS_TRADES)
        c.commit()
        # link consumers by exact paper_trade_id
        for tbl, col in PAPER_LINKS:
            cur.execute(f"""UPDATE {tbl} t SET trade_instance_id = ti.id FROM trade_instances ti
                WHERE ti.source_table='paper_trades' AND ti.source_trade_id = t.{col}::text
                  AND t.{col} IS NOT NULL AND t.trade_instance_id IS NULL""")
        # hermes via related_trade_id (paper_trades.id)
        cur.execute("""UPDATE hermes_research_intelligence h SET trade_instance_id = ti.id FROM trade_instances ti
            WHERE ti.source_table='paper_trades' AND ti.source_trade_id = h.related_trade_id::text
              AND h.related_trade_id IS NOT NULL AND h.trade_instance_id IS NULL""")
        # backtest + journal schwab rows via trade_key → schwab instances (exact)
        cur.execute("""UPDATE trade_backtest_results b SET trade_instance_id = ti.id FROM trade_instances ti
            WHERE ti.trade_key = b.trade_key AND ti.source_table='trades'
              AND b.trade_instance_id IS NULL AND b.trade_key IS NOT NULL""")
        cur.execute("""UPDATE journal_trade_reviews j SET trade_instance_id = ti.id FROM trade_instances ti
            WHERE ti.trade_key = j.trade_key AND ti.source_table='trades'
              AND j.trade_instance_id IS NULL AND j.trade_key IS NOT NULL""")
        # populate canonical trade_edge_comparison from paper_trade_edge_comparison
        cur.execute("""INSERT INTO trade_edge_comparison (trade_instance_id, source_trade_table, source_trade_id,
              expected_avg_r, expected_win_rate, realized_r, realized_pnl_pct, edge_delta_r, edge_assessment,
              backtest_assessment, expected_edge_source, comparison_source)
            SELECT e.trade_instance_id, 'paper_trades', e.paper_trade_id::text, e.expected_avg_r,
              e.expected_win_rate, e.realized_r, e.realized_pnl_pct, e.r_delta, e.edge_assessment,
              e.backtest_assessment, 'proposal_backtest_snapshot', 'paper_trade_edge_comparison'
            FROM paper_trade_edge_comparison e WHERE e.trade_instance_id IS NOT NULL
            ON CONFLICT (trade_instance_id) DO UPDATE SET edge_assessment=EXCLUDED.edge_assessment,
              backtest_assessment=EXCLUDED.backtest_assessment, realized_r=EXCLUDED.realized_r,
              edge_delta_r=EXCLUDED.edge_delta_r, updated_at=now()""")
        c.commit()

    def one(s):
        cur.execute(s); return cur.fetchone()["c"]
    rep = {"mode": "apply" if apply else "dry-run"}
    if one("select count(*) c from information_schema.tables where table_name='trade_instances'"):
        cur.execute("select source_system, count(*) n from trade_instances group by source_system order by n desc")
        rep["by_source_system"] = {r["source_system"]: r["n"] for r in cur.fetchall()}
        cur.execute("select execution_environment, count(*) n from trade_instances group by execution_environment")
        rep["by_environment"] = {r["execution_environment"]: r["n"] for r in cur.fetchall()}
        rep["total_trade_instances"] = one("select count(*) c from trade_instances")
        rep["strategy_id_coverage"] = one("select count(*) c from trade_instances where strategy_id is not null")
        rep["proposal_id_coverage"] = one("select count(*) c from trade_instances where proposal_id is not null")
        rep["signal_id_coverage"] = one("select count(*) c from trade_instances where signal_id is not null")
        rep["paper_trades_represented"] = one("select count(*) c from trade_instances where source_table='paper_trades'")
        rep["imported_represented"] = one("select count(*) c from trade_instances where source_table='trades'")
        for tbl, _ in PAPER_LINKS:
            rep[f"{tbl}.trade_instance_id"] = one(f"select count(*) c from {tbl} where trade_instance_id is not null")
        rep["hermes.trade_instance_id"] = one("select count(*) c from hermes_research_intelligence where trade_instance_id is not null")
        rep["trade_edge_comparison_rows"] = one("select count(*) c from trade_edge_comparison")
    print(json.dumps(rep, indent=2))
    c.close()


if __name__ == "__main__":
    main()
