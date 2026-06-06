#!/usr/bin/env python3
"""backfill_llm_review_provenance.py — EXACT provenance backfill for trade_llm_reviews.

Exact joins only (no fuzzy mutation):
  A. close_analysis (source=strategy_backtest_trades): backtest_trade_id -> sbt -> strategy_id, account
     (simulation; no real trade_instance).
  B. structured_backtest_eval: input_snapshot(symbol,open_date,close_date) -> trade_backtest_results 1:1
     -> trade_instance_id + (strategy_id, account from trade_instances).
  C. paper reviews: paper_trade_id -> trade_instance; fill strategy/account/source.
  D. any row already having trade_instance_id: fill missing strategy/account/source from trade_instances.
Adds additive provenance columns. Writes only trade_llm_reviews.

  python3 scripts/backfill_llm_review_provenance.py            # dry-run
  python3 scripts/backfill_llm_review_provenance.py --apply
"""
import os, sys, json, psycopg2, psycopg2.extras

ALTER = """
ALTER TABLE trade_llm_reviews
  ADD COLUMN IF NOT EXISTS source_system TEXT,
  ADD COLUMN IF NOT EXISTS source_trade_id TEXT,
  ADD COLUMN IF NOT EXISTS execution_broker TEXT,
  ADD COLUMN IF NOT EXISTS execution_environment TEXT,
  ADD COLUMN IF NOT EXISTS provenance_kind TEXT,
  ADD COLUMN IF NOT EXISTS provenance_confidence TEXT,
  ADD COLUMN IF NOT EXISTS provenance_notes TEXT,
  ADD COLUMN IF NOT EXISTS provenance_backfilled_at TIMESTAMPTZ;
"""

# A. simulation reviews via backtest_trade_id -> strategy_backtest_trades
SQL_A = """
UPDATE trade_llm_reviews r SET
  strategy_id = COALESCE(r.strategy_id, sbt.strategy_id), account = COALESCE(r.account, sbt.account),
  source_system='simulation', source_table='strategy_backtest_trades', source_trade_id=sbt.id::text,
  provenance_kind='simulation', provenance_confidence='exact_backtest_trade',
  provenance_notes='exact sbt.id join', provenance_backfilled_at=now()
FROM strategy_backtest_trades sbt
WHERE sbt.id = r.backtest_trade_id AND r.source_table='strategy_backtest_trades'
  AND r.provenance_kind IS NULL;
"""

# B. structured eval -> trade_backtest_results by exact (symbol, open_date, close_date) 1:1
SQL_B = """
UPDATE trade_llm_reviews r SET
  backtest_trade_id = m.tbr_id, trade_instance_id = m.ti_id,
  provenance_kind='imported_backtest',
  provenance_confidence = CASE WHEN m.ti_id IS NOT NULL THEN 'exact_trade_instance' ELSE 'exact_backtest_row_no_instance' END,
  provenance_notes='exact (symbol,open,close)->tbr', provenance_backfilled_at=now()
FROM (
  SELECT r2.id rid, b.id tbr_id, b.trade_instance_id ti_id
  FROM trade_llm_reviews r2
  JOIN trade_backtest_results b
    ON b.symbol = r2.input_snapshot->>'symbol'
   AND b.open_date::date = (r2.input_snapshot->>'open_date')::date
   AND b.close_date::date = (r2.input_snapshot->>'close_date')::date
  WHERE r2.review_stage='structured_backtest_eval' AND r2.provenance_kind IS NULL
    AND r2.input_snapshot ? 'symbol' AND r2.input_snapshot ? 'close_date'
  GROUP BY r2.id, b.id, b.trade_instance_id
  HAVING (SELECT COUNT(*) FROM trade_backtest_results b2
          WHERE b2.symbol=r2.input_snapshot->>'symbol'
            AND b2.open_date::date=(r2.input_snapshot->>'open_date')::date
            AND b2.close_date::date=(r2.input_snapshot->>'close_date')::date) = 1
) m WHERE m.rid = r.id;
"""

# C. paper reviews via paper_trade_id -> trade_instance
SQL_C = """
UPDATE trade_llm_reviews r SET trade_instance_id = ti.id, provenance_kind='paper',
  provenance_confidence='exact_paper_trade', provenance_notes='exact paper_trade_id->trade_instance',
  provenance_backfilled_at=now()
FROM trade_instances ti
WHERE ti.source_table='paper_trades' AND ti.source_trade_id = r.paper_trade_id::text
  AND r.paper_trade_id IS NOT NULL AND r.trade_instance_id IS NULL AND r.provenance_kind IS NULL;
"""

# D. fill strategy/account/source from trade_instance for any linked row still missing them
SQL_D = """
UPDATE trade_llm_reviews r SET
  strategy_id=COALESCE(r.strategy_id, ti.strategy_id), account=COALESCE(r.account, ti.execution_account),
  source_system=COALESCE(r.source_system, ti.source_system),
  source_trade_id=COALESCE(r.source_trade_id, ti.source_trade_id),
  execution_broker=COALESCE(r.execution_broker, ti.execution_broker),
  execution_environment=COALESCE(r.execution_environment, ti.execution_environment),
  provenance_kind=COALESCE(r.provenance_kind, CASE WHEN ti.source_table='paper_trades' THEN 'paper' ELSE 'imported_backtest' END),
  provenance_confidence=COALESCE(r.provenance_confidence,'exact_trade_instance')
FROM trade_instances ti
WHERE ti.id = r.trade_instance_id;
"""

# label the genuinely unlinkable
SQL_UNLINKED = """
UPDATE trade_llm_reviews SET provenance_kind=COALESCE(provenance_kind,
  CASE WHEN source_table='strategy_backtest_trades' THEN 'simulation' ELSE 'imported_backtest' END),
  provenance_confidence=COALESCE(provenance_confidence,'unlinked_imported_or_simulation'),
  provenance_notes=COALESCE(provenance_notes,'no exact source key available')
WHERE provenance_kind IS NULL;
"""


def main():
    apply = "--apply" in sys.argv
    c = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                         user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(ALTER); c.commit()  # additive columns are safe to ensure in both modes

    def cov():
        cur.execute("""select count(*) total,
          count(*) filter(where strategy_id is not null) strat, count(*) filter(where account is not null) acct,
          count(*) filter(where trade_instance_id is not null) ti, count(*) filter(where source_system is not null) ss,
          count(*) filter(where provenance_kind is not null) pk from trade_llm_reviews""")
        return dict(cur.fetchone())
    before = cov()
    if apply:
        for sql in (SQL_A, SQL_B, SQL_C, SQL_D, SQL_UNLINKED):
            cur.execute(sql)
        c.commit()
    after = cov()
    cur.execute("select coalesce(provenance_kind,'(null)') k, coalesce(provenance_confidence,'(null)') conf, count(*) n from trade_llm_reviews group by 1,2 order by 3 desc")
    by_prov = [dict(r) for r in cur.fetchall()]
    out = {"mode": "apply" if apply else "dry-run", "before": before, "after": after, "by_provenance": by_prov}
    print(json.dumps(out, indent=2, default=str))
    for flag in ("--json", "--markdown"):
        if flag in sys.argv:
            p = sys.argv[sys.argv.index(flag) + 1]
            open(p, "w").write(json.dumps(out, indent=2, default=str) if flag == "--json"
                               else "# LLM review provenance backfill\n\n```json\n" + json.dumps(out, indent=2, default=str) + "\n```")
    c.close()


if __name__ == "__main__":
    main()
