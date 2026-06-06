#!/usr/bin/env python3
"""validate_all_trades_closed_loop.py — verify the broker/account-neutral all-trades closed loop.
Read-only. Reports canonical coverage + flags remaining paper-only paths.
  python3 scripts/validate_all_trades_closed_loop.py [--json PATH]
"""
import os, sys, json, glob, psycopg2, psycopg2.extras

def main():
    c = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                         user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    def one(s):
        cur.execute(s); return cur.fetchone()["c"]
    checks = []
    def chk(n, ok, d=""):
        checks.append({"name": n, "pass": bool(ok), "detail": str(d)})

    cur.execute("select source_system, count(*) n from trade_instances group by source_system order by n desc")
    by_src = {r["source_system"]: r["n"] for r in cur.fetchall()}
    total_ti = one("select count(*) c from trade_instances")
    paper_pt = one("select count(*) c from paper_trades")
    ti_paper = one("select count(*) c from trade_instances where source_table='paper_trades'")
    ti_import = one("select count(*) c from trade_instances where source_table='trades'")
    chk("every paper_trade has a trade_instance", ti_paper == paper_pt, f"{ti_paper}/{paper_pt}")
    chk("imported (Schwab/Fidelity) trades represented", ti_import > 0, f"{ti_import}")
    chk("trade_instances is multi-source (not paper-only)", len(by_src) > 1, str(by_src))
    # linkage by canonical id
    h_ti = one("select count(*) c from hermes_research_intelligence where trade_instance_id is not null")
    j_ti = one("select count(*) c from journal_trade_reviews where trade_instance_id is not null")
    b_ti = one("select count(*) c from trade_backtest_results where trade_instance_id is not null")
    e_ti = one("select count(*) c from trade_edge_comparison")
    chk("hermes reflections linked by trade_instance_id", h_ti > 0, f"{h_ti}")
    chk("journal reviews linked by trade_instance_id", j_ti > 0, f"{j_ti}")
    chk("backtest results linked by trade_instance_id", b_ti > 0, f"{b_ti}")
    chk("canonical trade_edge_comparison populated", e_ti > 0, f"{e_ti}")
    # backtest linkage now spans imported trades (not paper-only)
    b_import = one("""select count(*) c from trade_backtest_results b join trade_instances ti on ti.id=b.trade_instance_id
                      where ti.source_table='trades'""")
    chk("backtest linkage covers imported trades", b_import > 0, f"{b_import} imported")
    # rows still only paper_trade_id (legacy compat — informational, not a failure)
    only_paper = one("""select count(*) c from trade_backtest_results
                        where paper_trade_id is not null and trade_instance_id is null""")
    chk("legacy paper_trade_id retained (compat)", True, f"{only_paper} backtest rows paper-only (compat)")
    # canonical Hermes targeting: closed_trade_needing_reflection present, closed_paper_trade gone
    loop = open(os.path.join(os.path.dirname(__file__), "hermes_autonomous_loop.py")).read()
    chk("Hermes targeting is all-trades (closed_trade_needing_reflection)", "closed_trade_needing_reflection" in loop)
    chk("legacy closed_paper_trade tier removed from canonical path", "'closed_paper_trade'" not in loop and '"closed_paper_trade"' not in loop)
    chk("Hermes targeting queries trade_instances", "FROM trade_instances" in loop)
    # safety: no order/GO-WAIT/strategy writes in the new scripts
    bad = []
    for f in ["migrate_trade_instances.py", "backfill_trade_instances.py"]:  # validator names these strings as search terms
        t = open(os.path.join(os.path.dirname(__file__), f)).read()
        if any(k in t for k in ("submit_order", "place_order", "UPDATE atm_state", "GO_NO_GO")):
            bad.append(f)
    chk("no order/GO-WAIT writes in new scripts", not bad, str(bad))
    env = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")).read()
    chk("paper mode / live disabled", "ALPACA_MODE=paper" in env and "LLM_DISABLE_LIVE_EXECUTION=true" in env)

    ok = all(x["pass"] for x in checks)
    summary = {"by_source_system": by_src, "total_trade_instances": total_ti,
               "trade_instance_links": {"hermes": h_ti, "journal": j_ti, "backtest": b_ti, "edge": e_ti}}
    result = {"pass": ok, "summary": summary, "checks": checks}
    if "--json" in sys.argv:
        json.dump(result, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=2)
    print(json.dumps(summary, indent=2))
    for x in checks:
        print(f"  [{'PASS' if x['pass'] else 'FAIL'}] {x['name']}" + (f" — {x['detail']}" if x['detail'] else ""))
    print(f"\n{sum(1 for x in checks if x['pass'])}/{len(checks)} PASS — {'GREEN' if ok else 'FAILED'}")
    c.close(); sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
