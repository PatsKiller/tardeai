#!/usr/bin/env python3
"""compute_edge_comparison.py — Step 4: post-exit backtest comparison.

For each CLOSED paper_trade that had a proposal_backtest_snapshot (the proposal-time expected edge),
record realized outcome vs expected edge in `paper_trade_edge_comparison` (additive, append/upsert).
NO_DATA snapshots (no historical samples) → edge_assessment='no_expected_edge' (never fabricated).
Read-only w.r.t. trading; analysis only. Run post-close (on demand or cron).

  python3 scripts/compute_edge_comparison.py            # dry-run (counts)
  python3 scripts/compute_edge_comparison.py --apply
"""
import os, sys, json, psycopg2, psycopg2.extras

DDL = """
CREATE TABLE IF NOT EXISTS paper_trade_edge_comparison (
  id SERIAL PRIMARY KEY,
  paper_trade_id BIGINT UNIQUE,
  proposal_id INTEGER,
  symbol TEXT,
  strategy_id TEXT,
  expected_win_rate NUMERIC,
  expected_avg_r NUMERIC,
  expected_expectancy NUMERIC,
  expected_sample_size INTEGER,
  expected_backtest_quality TEXT,
  realized_verdict TEXT,
  realized_r NUMERIC,
  realized_pnl_pct NUMERIC,
  realized_hold_min NUMERIC,
  r_delta NUMERIC,
  edge_assessment TEXT,
  bt_entry_grade TEXT,
  bt_overall_grade TEXT,
  bt_better_entry_existed BOOLEAN,
  bt_left_on_table_20d NUMERIC,
  bt_exit_was_early BOOLEAN,
  bt_data_quality TEXT,
  backtest_assessment TEXT,
  notes JSONB DEFAULT '{}'::jsonb,
  computed_at TIMESTAMPTZ DEFAULT now()
);
"""

ALTER = """
ALTER TABLE paper_trade_edge_comparison
  ADD COLUMN IF NOT EXISTS bt_entry_grade TEXT,
  ADD COLUMN IF NOT EXISTS bt_overall_grade TEXT,
  ADD COLUMN IF NOT EXISTS bt_better_entry_existed BOOLEAN,
  ADD COLUMN IF NOT EXISTS bt_left_on_table_20d NUMERIC,
  ADD COLUMN IF NOT EXISTS bt_exit_was_early BOOLEAN,
  ADD COLUMN IF NOT EXISTS bt_data_quality TEXT,
  ADD COLUMN IF NOT EXISTS backtest_assessment TEXT;
"""


def _conn():
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                            user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])


def _f(v):
    return float(v) if v is not None else None


def main():
    apply = "--apply" in sys.argv
    c = _conn(); cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if apply:
        cur.execute(DDL); cur.execute(ALTER); c.commit()
    # Base = ALL closed paper trades. LEFT JOIN the proposal-time expected edge (snapshot) AND the
    # per-trade entry-quality backtest (trade_backtest_results, linked by paper_trade_id in Step 3).
    cur.execute("""
        SELECT DISTINCT ON (p.id) p.id AS paper_trade_id, p.proposal_id, p.symbol, p.strategy_id,
               p.outcome_verdict, p.r_multiple, p.pnl_pct, p.hold_time_min,
               b.win_rate, b.avg_r, b.expectancy, b.sample_size, b.backtest_quality,
               tbr.entry_grade, tbr.overall_grade, tbr.better_entry_existed,
               tbr.left_on_table_20d, tbr.exit_was_early, tbr.data_quality AS bt_dq
        FROM paper_trades p
        LEFT JOIN proposal_backtest_snapshots b ON b.proposal_id = p.proposal_id
        LEFT JOIN trade_backtest_results tbr ON tbr.paper_trade_id = p.id
        WHERE (lower(coalesce(p.status,''))='closed' OR p.exit_time IS NOT NULL)
        ORDER BY p.id, b.created_at DESC
    """)
    rows = cur.fetchall()
    counts = {"total": len(rows), "edge_compared": 0, "no_expected_edge": 0, "phantom_skipped": 0,
              "backtest_compared": 0, "no_per_trade_backtest": 0}
    by_assessment, by_bt = {}, {}
    for r in rows:
        verdict = (r["outcome_verdict"] or "").upper()
        exp_r = _f(r["avg_r"])
        realized_r = _f(r["r_multiple"])
        r_delta = (realized_r - exp_r) if (realized_r is not None and exp_r is not None) else None
        # ── A. proposal-snapshot expected-edge comparison ──
        if verdict == "PHANTOM":
            assessment = "phantom_no_outcome"
            counts["phantom_skipped"] += 1
        elif exp_r is None:
            assessment = "no_expected_edge"
            counts["no_expected_edge"] += 1
        elif realized_r is None:
            assessment = "no_realized_r"
        else:
            assessment = ("outperformed_backtest" if r_delta > 0.25 else
                          "underperformed_backtest" if r_delta < -0.25 else "in_line_with_backtest")
            counts["edge_compared"] += 1
        by_assessment[assessment] = by_assessment.get(assessment, 0) + 1
        # ── B. per-trade entry-quality backtest comparison (trade_backtest_results) ──
        bt_dq = (r["bt_dq"] or "").lower()
        be, ee = r["better_entry_existed"], r["exit_was_early"]
        if r["entry_grade"] is None and not bt_dq:
            bt_assess = "no_per_trade_backtest"
            counts["no_per_trade_backtest"] += 1
        elif bt_dq == "insufficient":
            bt_assess = "backtest_insufficient"
        else:
            bt_assess = ("better_entry_and_early_exit" if (be and ee) else
                         "better_entry_existed" if be else
                         "exited_early" if ee else "entry_exit_optimal")
            counts["backtest_compared"] += 1
        by_bt[bt_assess] = by_bt.get(bt_assess, 0) + 1
        if apply:
            cur.execute("""
                INSERT INTO paper_trade_edge_comparison
                  (paper_trade_id, proposal_id, symbol, strategy_id, expected_win_rate, expected_avg_r,
                   expected_expectancy, expected_sample_size, expected_backtest_quality, realized_verdict,
                   realized_r, realized_pnl_pct, realized_hold_min, r_delta, edge_assessment,
                   bt_entry_grade, bt_overall_grade, bt_better_entry_existed, bt_left_on_table_20d,
                   bt_exit_was_early, bt_data_quality, backtest_assessment, notes, computed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (paper_trade_id) DO UPDATE SET
                  expected_avg_r=EXCLUDED.expected_avg_r, expected_backtest_quality=EXCLUDED.expected_backtest_quality,
                  realized_verdict=EXCLUDED.realized_verdict, realized_r=EXCLUDED.realized_r,
                  realized_pnl_pct=EXCLUDED.realized_pnl_pct, r_delta=EXCLUDED.r_delta,
                  edge_assessment=EXCLUDED.edge_assessment, bt_entry_grade=EXCLUDED.bt_entry_grade,
                  bt_overall_grade=EXCLUDED.bt_overall_grade, bt_better_entry_existed=EXCLUDED.bt_better_entry_existed,
                  bt_left_on_table_20d=EXCLUDED.bt_left_on_table_20d, bt_exit_was_early=EXCLUDED.bt_exit_was_early,
                  bt_data_quality=EXCLUDED.bt_data_quality, backtest_assessment=EXCLUDED.backtest_assessment,
                  computed_at=now()
            """, (r["paper_trade_id"], r["proposal_id"], r["symbol"], r["strategy_id"], _f(r["win_rate"]), exp_r,
                  _f(r["expectancy"]), r["sample_size"], r["backtest_quality"], verdict or None, realized_r,
                  _f(r["pnl_pct"]), _f(r["hold_time_min"]), r_delta, assessment,
                  r["entry_grade"], r["overall_grade"], be, _f(r["left_on_table_20d"]), ee, r["bt_dq"], bt_assess,
                  json.dumps({"realized_win": verdict == "WIN"})))
    if apply:
        c.commit()
    print(json.dumps({"mode": "apply" if apply else "dry-run", **counts,
                      "edge_by_assessment": by_assessment, "backtest_by_assessment": by_bt}, indent=2))
    c.close()


if __name__ == "__main__":
    main()
