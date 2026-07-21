#!/usr/bin/env python3
"""populate_imported_trade_edge_comparison.py — canonical edge comparison for IMPORTED trades.

Imported trades (Schwab/Fidelity/future broker) generally lack a proposal-time expected edge. Their
canonical edge comparison uses PER-TRADE BACKTEST evidence (trade_backtest_results), NOT fabricated
proposal snapshots. Writes only to trade_edge_comparison; never overwrites existing proposal-edge rows.
Broker/account-neutral: any source_system except alpaca_paper (paper is handled by the proposal path).

  python3 scripts/populate_imported_trade_edge_comparison.py            # dry-run
  python3 scripts/populate_imported_trade_edge_comparison.py --apply
"""
import os, sys, json, psycopg2, psycopg2.extras


def _conn():
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                            user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])


def _bt_assessment(be, ee, dq):
    if (dq or "").lower() == "insufficient":
        return "insufficient_backtest"
    if be and ee:
        return "better_entry_and_early_exit"
    if be:
        return "better_entry_existed"
    if ee:
        return "exited_early"
    return "entry_exit_optimal"


def _f(v):
    return float(v) if v is not None else None


def main():
    apply = "--apply" in sys.argv
    c = _conn(); cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT ti.id AS trade_instance_id, ti.source_system, ti.source_table, ti.source_trade_id, ti.symbol,
               ti.r_multiple, ti.pnl_pct, br.id AS bt_id, br.entry_grade, br.exit_grade, br.overall_grade,
               br.better_entry_existed, br.exit_was_early, br.left_on_table_20d, br.data_quality
        FROM trade_instances ti
        JOIN trade_backtest_results br ON br.trade_instance_id = ti.id
        LEFT JOIN trade_edge_comparison ec ON ec.trade_instance_id = ti.id
        WHERE lower(coalesce(ti.status,'')) = 'closed'
          AND ti.source_system <> 'tradeai_automated'
          AND ec.trade_instance_id IS NULL
        ORDER BY ti.id
    """)
    rows = cur.fetchall()
    counts = {"candidates": len(rows), "written": 0, "missing_realized": 0, "insufficient_backtest": 0}
    by_assess, samples = {}, []
    for r in rows:
        bt = _bt_assessment(r["better_entry_existed"], r["exit_was_early"], r["data_quality"])
        realized_r, realized_pnl = _f(r["r_multiple"]), _f(r["pnl_pct"])
        if (r["data_quality"] or "").lower() == "insufficient":
            counts["insufficient_backtest"] += 1
        if realized_r is None and realized_pnl is None:
            counts["missing_realized"] += 1
        # edge_assessment mirrors the per-trade backtest verdict (no expected edge → never fabricated)
        edge = bt
        by_assess[edge] = by_assess.get(edge, 0) + 1
        if len(samples) < 6:
            samples.append({"symbol": r["symbol"], "source": r["source_system"], "entry_grade": r["entry_grade"],
                            "overall_grade": r["overall_grade"], "better_entry": r["better_entry_existed"],
                            "exited_early": r["exit_was_early"], "realized_r": realized_r, "assessment": bt})
        if apply:
            cur.execute("""
                INSERT INTO trade_edge_comparison
                  (trade_instance_id, source_trade_table, source_trade_id, proposal_snapshot_id,
                   trade_backtest_result_id, expected_edge_source, expected_avg_r, expected_win_rate,
                   realized_r, realized_pnl_pct, edge_delta_r, edge_assessment, backtest_assessment, comparison_source)
                VALUES (%s,%s,%s,NULL,%s,'per_trade_backtest',NULL,NULL,%s,%s,NULL,%s,%s,'imported_trade_backtest')
                ON CONFLICT (trade_instance_id) DO NOTHING
            """, (r["trade_instance_id"], r["source_table"], r["source_trade_id"], r["bt_id"],
                  realized_r, realized_pnl, edge, bt))
            counts["written"] += 1
    if apply:
        c.commit()

    def one(s):
        cur.execute(s); return cur.fetchone()["c"]
    after = {"total_edge_rows": one("select count(*) c from trade_edge_comparison")}
    cur.execute("""select coalesce(ti.source_system,'(none)') s, count(*) n from trade_edge_comparison e
                   left join trade_instances ti on ti.id=e.trade_instance_id group by 1 order by 2 desc""")
    after["by_source_system"] = {r["s"]: r["n"] for r in cur.fetchall()}
    out = {"mode": "apply" if apply else "dry-run", **counts, "edge_by_assessment": by_assess,
           "after": after, "samples": samples}
    print(json.dumps(out, indent=2, default=str))
    if "--json" in sys.argv:
        json.dump(out, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=2, default=str)
    c.close()


if __name__ == "__main__":
    main()
