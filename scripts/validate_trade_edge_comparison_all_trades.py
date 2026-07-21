#!/usr/bin/env python3
"""validate_trade_edge_comparison_all_trades.py — verify canonical edge comparison spans all sources.
Read-only.  python3 scripts/validate_trade_edge_comparison_all_trades.py [--json PATH]
"""
import os, sys, json, psycopg2, psycopg2.extras


def main():
    c = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                         user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    def one(s):
        cur.execute(s); return cur.fetchone()["c"]
    rep = {}
    rep["total"] = one("select count(*) c from trade_edge_comparison")
    cur.execute("""select coalesce(ti.source_system,'(none)') s, count(*) n from trade_edge_comparison e
                   left join trade_instances ti on ti.id=e.trade_instance_id group by 1 order by 2 desc""")
    rep["by_source_system"] = {r["s"]: r["n"] for r in cur.fetchall()}
    rep["paper_rows"] = one("select count(*) c from trade_edge_comparison e join trade_instances ti on ti.id=e.trade_instance_id where ti.source_system='tradeai_automated'")
    rep["imported_schwab_rows"] = one("select count(*) c from trade_edge_comparison e join trade_instances ti on ti.id=e.trade_instance_id where ti.source_system='schwab_import'")
    rep["imported_fidelity_rows"] = one("select count(*) c from trade_edge_comparison e join trade_instances ti on ti.id=e.trade_instance_id where ti.source_system='fidelity_import'")
    rep["rows_with_proposal_snapshot"] = one("select count(*) c from trade_edge_comparison where proposal_snapshot_id is not null")
    rep["rows_per_trade_backtest_only"] = one("select count(*) c from trade_edge_comparison where expected_edge_source='per_trade_backtest'")
    rep["rows_missing_realized"] = one("select count(*) c from trade_edge_comparison where realized_r is null and realized_pnl_pct is null")
    rep["rows_insufficient_backtest"] = one("select count(*) c from trade_edge_comparison where backtest_assessment='insufficient_backtest'")
    rep["rows_better_entry_existed"] = one("select count(*) c from trade_edge_comparison where backtest_assessment in ('better_entry_existed','better_entry_and_early_exit')")
    rep["rows_exited_early"] = one("select count(*) c from trade_edge_comparison where backtest_assessment in ('exited_early','better_entry_and_early_exit')")
    rep["duplicate_trade_instance_id"] = one("select coalesce(sum(c-1),0) c from (select trade_instance_id, count(*) c from trade_edge_comparison where trade_instance_id is not null group by 1 having count(*)>1) x")
    rep["imported_fake_expected_edge"] = one("select count(*) c from trade_edge_comparison where expected_edge_source='per_trade_backtest' and (expected_avg_r is not null or expected_win_rate is not null)")

    checks = []
    def chk(n, ok, d=""):
        checks.append({"name": n, "pass": bool(ok), "detail": str(d)})
    chk("imported backtest candidates represented", rep["imported_schwab_rows"] > 0, rep["imported_schwab_rows"])
    chk("paper rows preserved", rep["paper_rows"] >= 43, rep["paper_rows"])
    chk("edge comparison is multi-source", len([k for k, v in rep["by_source_system"].items() if v > 0]) > 1, rep["by_source_system"])
    chk("no duplicate trade_instance_id", rep["duplicate_trade_instance_id"] == 0, rep["duplicate_trade_instance_id"])
    chk("no fabricated expected edge for imported", rep["imported_fake_expected_edge"] == 0, rep["imported_fake_expected_edge"])
    chk("per-trade-backtest comparisons present", rep["rows_per_trade_backtest_only"] > 0, rep["rows_per_trade_backtest_only"])
    env = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")).read()
    chk("paper mode / live disabled", "ALPACA_MODE=paper" in env and "LLM_DISABLE_LIVE_EXECUTION=true" in env)

    ok = all(x["pass"] for x in checks)
    print(json.dumps(rep, indent=2, default=str))
    for x in checks:
        print(f"  [{'PASS' if x['pass'] else 'FAIL'}] {x['name']}" + (f" — {x['detail']}" if x['detail'] else ""))
    print(f"\n{sum(1 for x in checks if x['pass'])}/{len(checks)} PASS — {'GREEN' if ok else 'FAILED'}")
    if "--json" in sys.argv:
        json.dump({"report": rep, "checks": checks, "pass": ok}, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=2, default=str)
    c.close(); sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
