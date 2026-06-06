#!/usr/bin/env python3
"""backfill_llm_review_provenance.py — link trade_llm_reviews to canonical trade_instance_id where it
exists, and report provenance kinds. Additive/reversible (sets trade_instance_id from NULL only).

Provenance kinds (derived, not stored):
  paper             source_table=paper_trades            -> trade_instance via paper_trade_id
  imported_backtest source_table=trade_backtest_results  -> trade_instance via backtest_trade_id->tbr.trade_instance_id
  simulation        source_table=strategy_backtest_trades-> NO real trade_instance (sim rows; left NULL, honest)

  python3 scripts/backfill_llm_review_provenance.py            # dry-run
  python3 scripts/backfill_llm_review_provenance.py --apply
"""
import os, sys, json, psycopg2, psycopg2.extras


def main():
    apply = "--apply" in sys.argv
    c = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                         user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if apply:
        # paper reviews -> trade_instance via paper_trade_id
        cur.execute("""UPDATE trade_llm_reviews r SET trade_instance_id = ti.id
            FROM trade_instances ti
            WHERE ti.source_table='paper_trades' AND ti.source_trade_id = r.paper_trade_id::text
              AND r.paper_trade_id IS NOT NULL AND r.trade_instance_id IS NULL""")
        # imported-backtest reviews -> trade_instance via backtest_trade_id -> trade_backtest_results
        cur.execute("""UPDATE trade_llm_reviews r SET trade_instance_id = b.trade_instance_id
            FROM trade_backtest_results b
            WHERE r.source_table='trade_backtest_results' AND r.backtest_trade_id = b.id
              AND b.trade_instance_id IS NOT NULL AND r.trade_instance_id IS NULL""")
        c.commit()

    def one(s):
        cur.execute(s); return cur.fetchone()["c"]
    rep = {"mode": "apply" if apply else "dry-run",
           "total": one("select count(*) c from trade_llm_reviews"),
           "trade_instance_linked": one("select count(*) c from trade_llm_reviews where trade_instance_id is not null"),
           "by_source_kind": {}}
    cur.execute("""select case source_table
                     when 'paper_trades' then 'paper'
                     when 'trade_backtest_results' then 'imported_backtest'
                     when 'strategy_backtest_trades' then 'simulation'
                     else coalesce(source_table,'unknown') end kind,
                   count(*) n, count(trade_instance_id) linked
                   from trade_llm_reviews group by 1 order by 2 desc""")
    rep["by_source_kind"] = {r["kind"]: {"rows": r["n"], "trade_instance_linked": r["linked"]} for r in cur.fetchall()}
    print(json.dumps(rep, indent=2))
    c.close()


if __name__ == "__main__":
    main()
