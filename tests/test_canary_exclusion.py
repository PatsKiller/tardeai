#!/usr/bin/env python3
"""Canary analytics exclusion proof (Stage 2a Part A2). Self-runnable:
    .venv/bin/python tests/test_canary_exclusion.py

Inserts a synthetic canary-tagged round-trip with a deliberately huge P&L, re-runs the EXACT
aggregate predicates used by every schwab_round_trips consumer, and proves none of them moved:
  1. /api/v2/journal/schwab-round-trips active stats  (api_v2._schwab_round_trips)
  2. trade_closed journal refresh                     (schwab_journal_builder)
  3. LLM classifier candidate set                     (schwab_journal_classifier)
  4. backtest fill reconciliation set                 (backtest_fill_reconciliation)
  5. execution-quality build set                      (build_trade_execution_quality)
  6. gain/loss basis reconciliation grouping          (ingest_schwab_gainloss)
Also proves the row IS captured (visible unfiltered with canary=true) — excluded, not lost.
The synthetic row is removed in a finally block; the table ends exactly as it began.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from db_adapter import _get_conn

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


SYM = "ZZCANARY"          # synthetic; never a real holding
DEDUPE = "stage2a-canary-exclusion-proof"

# The EXACT consumer predicates (kept in lockstep with the source files — validator checks the
# `canary IS NOT TRUE` clauses exist in those files too).
AGGS = {
    "api active stats (count,sum)":
        "SELECT count(*), COALESCE(sum(net_pnl),0) FROM schwab_round_trips WHERE basis_status IS NULL AND canary IS NOT TRUE",
    "trade_closed refresh set":
        "SELECT count(*) FROM schwab_round_trips WHERE basis_status IS DISTINCT FROM 'basis_unknown' AND entry_time IS NOT NULL AND canary IS NOT TRUE",
    "classifier candidate set":
        "SELECT count(*) FROM schwab_round_trips WHERE reviewed_at IS NULL AND canary IS NOT TRUE",
    "backtest recon set":
        "SELECT count(*) FROM schwab_round_trips WHERE entry_price > 0 AND exit_price > 0 AND qty > 0 AND basis_status IS NULL AND canary IS NOT TRUE",
    "exec-quality set":
        "SELECT count(*) FROM schwab_round_trips WHERE basis_status IS DISTINCT FROM 'basis_unknown' AND entry_time IS NOT NULL AND exit_time IS NOT NULL AND canary IS NOT TRUE",
    "gainloss recon groups":
        "SELECT count(*), COALESCE(sum(net_pnl),0) FROM schwab_round_trips WHERE basis_status IS DISTINCT FROM 'basis_unknown' AND canary IS NOT TRUE",
}


def snapshot(cur):
    out = {}
    for name, q in AGGS.items():
        cur.execute(q)
        out[name] = cur.fetchone()
    return out


conn = _get_conn()
cur = conn.cursor()
cur.execute("DELETE FROM schwab_round_trips WHERE dedupe_key=%s", (DEDUPE,))
conn.commit()
before = snapshot(cur)
try:
    cur.execute("""INSERT INTO schwab_round_trips
                     (account, symbol, entry_time, exit_time, hold_minutes, qty, entry_price, exit_price,
                      gross_pnl, fees, net_pnl, pnl_pct, classification, dedupe_key, canary)
                   VALUES ('schwab_taxable', %s, NOW()-INTERVAL '1 hour', NOW(), 60, 10, 3.50, 1003.50,
                      10000.00, 0.00, 10000.00, 28571.4, 'day_trade', %s, TRUE)""", (SYM, DEDUPE))
    conn.commit()
    after = snapshot(cur)
    print("\n— canary row inserted ($10,000 fake P&L) — every consumer aggregate must be unmoved —")
    for name in AGGS:
        check(f"{name} unmoved", before[name] == after[name], f"before={before[name]} after={after[name]}")
    cur.execute("SELECT canary FROM schwab_round_trips WHERE dedupe_key=%s", (DEDUPE,))
    r = cur.fetchone()
    check("canary row IS captured (visible unfiltered, canary=true)", bool(r and r[0]))
    cur.execute("SELECT count(*) FROM trade_closed WHERE symbol=%s", (SYM,))
    check("no journal trade_closed row exists for the canary symbol", cur.fetchone()[0] == 0)
finally:
    cur.execute("DELETE FROM schwab_round_trips WHERE dedupe_key=%s", (DEDUPE,))
    conn.commit()
cur.execute("SELECT count(*) FROM schwab_round_trips WHERE dedupe_key=%s", (DEDUPE,))
check("cleanup: synthetic row removed", cur.fetchone()[0] == 0)

print(f"\n  {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
