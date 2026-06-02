#!/usr/bin/env python3
"""Phase 190G — PENDING_TRADING_WINDOW analyzer (ADVISORY / dry-run only).

Identifies proposals generated outside a valid trading window that are looping
through delayed-revalidation (e.g. premarket scalps like ELMT). Reports what a
PENDING_TRADING_WINDOW lifecycle WOULD park/dedup. It does NOT mutate proposal
status and does NOT touch GO/WAIT/approval logic — wiring into the approver is a
separate, operator-approved step.
"""
import os, sys, json
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def load_env():
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def run():
    load_env()
    try:
        from market_session import current_market_session, should_delay_execution
        session = current_market_session()
    except Exception:
        session = "unknown"
    conn = db(); cur = conn.cursor()
    # Active proposals that would be parked: pre-open/stale, not terminal.
    cur.execute("""select id,symbol,strategy_id,status,action_state,created_at,
                          updated_at,proposed_entry
                   from paper_trade_proposals
                   where status in ('PENDING','MODIFIED','APPROVED_FOR_PAPER_TEST')
                   order by created_at desc""")
    rows = cur.fetchall()
    candidates, dup_groups = [], {}
    for (pid, sym, strat, status, astate, created, updated, entry) in rows:
        delayed = False
        try:
            delayed, _reason = should_delay_execution(strat)
        except Exception:
            pass
        rec = {"id": pid, "symbol": sym, "strategy": strat, "status": status,
               "action_state": astate, "session": session, "would_park": bool(delayed)}
        candidates.append(rec)
        key = f"{sym}:{strat}"
        dup_groups.setdefault(key, []).append(pid)
    duplicates = {k: v for k, v in dup_groups.items() if len(v) > 1}
    report = {"run_at": datetime.now(timezone.utc).isoformat(), "market_session": session,
              "active_proposals": len(rows),
              "would_park_pending_trading_window": [c for c in candidates if c["would_park"]],
              "duplicate_symbol_strategy_groups": duplicates,
              "note": "ADVISORY ONLY — no status mutated; approver wiring is a separate approved step."}
    conn.close()
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
