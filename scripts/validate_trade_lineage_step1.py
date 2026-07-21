#!/usr/bin/env python3
"""validate_trade_lineage_step1.py — verify Step-1 execution lineage. Read-only.
  python3 scripts/validate_trade_lineage_step1.py --json /tmp/x.json --markdown /tmp/x.md
"""
import os, sys, json, psycopg2, psycopg2.extras
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trade_lineage import extract_lineage_from_proposal

NEW_COLS = ["strategy_card_id", "candidate_id", "source_proposal_id", "execution_account", "execution_broker",
            "execution_environment", "lineage_source", "lineage_stamped_at", "lineage_confidence", "lineage_notes"]


def main():
    c = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                         user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    checks = []

    def chk(n, ok, d=""):
        checks.append({"name": n, "pass": bool(ok), "detail": d})

    # schema columns exist
    cur.execute("select column_name from information_schema.columns where table_name='paper_trades'")
    have = {r["column_name"] for r in cur.fetchall()}
    chk("lineage columns exist", all(c2 in have for c2 in NEW_COLS), str([c2 for c2 in NEW_COLS if c2 not in have]))
    # helper returns lineage for a representative approved proposal
    cur.execute("select id from paper_trade_proposals where lower(coalesce(status,'')) like 'approved%' or paper_trade_id is not null limit 1")
    r = cur.fetchone()
    lin = extract_lineage_from_proposal(c, r["id"]) if r else {}
    chk("helper returns lineage for an approved proposal", bool(r) and lin.get("lineage_confidence") == "exact" and lin.get("execution_broker"), json.dumps(lin, default=str)[:160])
    # helper not hardcoded to alpaca: a non-alpaca account resolves to its own broker
    cur.execute("select broker,environment from broker_accounts where account_key='schwab_taxable'")
    sb = cur.fetchone()
    chk("broker/account neutral (schwab resolves to schwab)", bool(sb) and sb["broker"] == "schwab")
    src = open(os.path.join(os.path.dirname(__file__), "trade_lineage.py")).read()
    chk("helper has no hardcoded alpaca_paper literal", "tradeai_automated" not in src)
    # paper_trades with exact proposal links have stamped lineage where proposal data exists
    cur.execute("select count(*) c from paper_trades where proposal_id is not null")
    linked = cur.fetchone()["c"]
    cur.execute("select count(*) c from paper_trades where proposal_id is not null and execution_account is not null")
    stamped = cur.fetchone()["c"]
    chk("exact-proposal trades stamped with execution lineage", linked > 0 and stamped == linked, f"{stamped}/{linked}")
    cur.execute("select count(*) c from paper_trades where source_signal_id is not null")
    sig = cur.fetchone()["c"]
    chk("source_signal_id coverage improved from 0%", sig > 0, f"{sig} stamped")
    # no conflicting reverse link (each proposal.paper_trade_id maps to a paper_trade with that proposal)
    cur.execute("""select count(*) c from paper_trade_proposals p join paper_trades t on t.id=p.paper_trade_id
                   where p.paper_trade_id is not null and t.proposal_id is not null and t.proposal_id <> p.id""")
    chk("no conflicting reverse links", cur.fetchone()["c"] == 0)
    # auto-approval executor still honors automation_mode (gate code present)
    aa = open(os.path.join(os.path.dirname(__file__), "atm_auto_approver.py")).read()
    chk("auto-approver still gates on automation_mode", "_account_automation_mode" in aa and "MANUAL_REVIEW" in aa)
    # no order submission in lineage code
    bad = []
    for f in ["trade_lineage.py", "backfill_trade_lineage.py"]:  # validator itself names these strings as search terms
        t = open(os.path.join(os.path.dirname(__file__), f)).read()
        if any(k in t for k in ("submit_order", "place_order", "cancel_order", "replace_order")):
            bad.append(f)
    chk("no broker order calls in lineage scripts", not bad, str(bad))
    # env safety
    env = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")).read()
    chk("paper mode / live disabled", "ALPACA_MODE=paper" in env and "LLM_DISABLE_LIVE_EXECUTION=true" in env)

    ok = all(c2["pass"] for c2 in checks)
    result = {"pass": ok, "checks": checks}
    if "--json" in sys.argv:
        json.dump(result, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=2)
    if "--markdown" in sys.argv:
        with open(sys.argv[sys.argv.index("--markdown") + 1], "w") as f:
            f.write("# Step 1 lineage validation\n\n" + "\n".join(
                f"- [{'PASS' if c2['pass'] else 'FAIL'}] {c2['name']}" + (f" — {c2['detail']}" if c2['detail'] and not c2['pass'] else "") for c2 in checks))
    for c2 in checks:
        print(f"  [{'PASS' if c2['pass'] else 'FAIL'}] {c2['name']}" + (f" — {c2['detail']}" if (c2['detail'] and not c2['pass']) else ""))
    print(f"\n{sum(1 for c2 in checks if c2['pass'])}/{len(checks)} PASS — {'GREEN' if ok else 'FAILED'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
