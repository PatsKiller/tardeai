#!/usr/bin/env python3
"""validate_schwab_no_writes.py — regression guard (Phase 1, proof artifact #4 + Rule 9).

Proves, mechanically:
  1. No reachable Schwab WRITE/order path (adapter write methods return NOT_PROVEN; broker_confirm_schwab.py absent).
  2. Schwab accounts keep api_write_enabled=false.
  3. live_trading_interlock refuses Schwab live accounts.
  4. LEVEL II ISOLATION (Rule 9): no path lets Level-II/volume-sweep advisory data touch the screeners
     (prime_setups / watchlist_setups), strategy match-minimums, GO/WAIT, or ATM routing.

Exit 0 = all green. Non-zero = a guard tripped (a regression).
"""
from __future__ import annotations
import os, re, subprocess, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
checks = []


def ok(name, passed, detail=""):
    checks.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}{' — ' + detail if detail else ''}")


# 1. broker_confirm_schwab.py must NOT exist (the write blocker stays unbuilt)
ok("broker_confirm_schwab.py absent (no write path)", not (SCRIPTS / "broker_confirm_schwab.py").exists())

# 2. schwab_adapter write methods unreachable / NOT_PROVEN
adapter = (SCRIPTS / "schwab_adapter.py").read_text() if (SCRIPTS / "schwab_adapter.py").exists() else ""
write_methods = re.findall(r"def (place_order|submit_order|submit_entry|cancel_order|replace_order|modify_stop|_api_post|confirm[_a-z]*)\b", adapter)
if write_methods:
    # each must raise/return NOT_PROVEN
    bad = []
    for m in set(write_methods):
        body = re.search(rf"def {m}\b.*?(?=\n    def |\nclass |\Z)", adapter, re.S)
        if body and "NOT_PROVEN" not in body.group(0):
            bad.append(m)
    ok("schwab_adapter write methods all NOT_PROVEN", not bad, f"unguarded: {bad}" if bad else f"{len(set(write_methods))} guarded")
else:
    ok("schwab_adapter exposes no order-write methods", True)

# 3. position-sync never reaches a live write without the guard
psync = (SCRIPTS / "schwab_position_sync.py").read_text() if (SCRIPTS / "schwab_position_sync.py").exists() else ""
ok("position sync routes writes through protected_holdings_write", "protected_holdings_write" in psync and "os.replace" in psync)
ok("position sync live fetch is NOT_PROVEN (fail closed)", "NOT_PROVEN" in psync)

# 4. Schwab accounts conservative (api_write_enabled=false) + interlock refuses them
try:
    sys.path.insert(0, str(SCRIPTS))
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("SELECT account_key, api_write_enabled FROM broker_accounts WHERE broker ILIKE '%schwab%'")
    rows = cur.fetchall()
    ok("all Schwab accounts api_write_enabled=false", all(not r[1] for r in rows), f"{len(rows)} schwab accounts" if rows else "none seeded yet")
    # interlock refuses a Schwab live account. Use the fast account_mode + master-flag path (gate_status
    # scans all paper_trades and can block on an unrelated lock — not needed to prove refusal).
    try:
        import live_trading_interlock as lti
        cur.execute("SELECT live_trading_allowed FROM paper_validation_policy WHERE active=true ORDER BY id DESC LIMIT 1")
        fr = cur.fetchone(); live_allowed = bool(fr[0]) if fr else False
        modes = {ak: lti.account_mode(conn, ak) for ak, _ in (rows or [])}
        # refusal holds iff no Schwab account is classified 'paper' (they're 'live'/unknown) AND the
        # master live-trading flag is OFF (live + not-allowed => assert_writable raises InterlockRefused)
        none_paper = all(m != "paper" for m in modes.values()) if modes else True
        ok("live_trading_interlock refuses Schwab (live + master flag OFF)", none_paper and not live_allowed,
           f"modes={modes} live_allowed={live_allowed}")
    except Exception as e:
        ok("interlock importable", False, str(e)[:60])
except Exception as e:
    ok("DB checks", False, str(e)[:60])

# 5. LEVEL II ISOLATION (Rule 9): no Schwab/Level-II/volume artifact feeds the screeners or routing.
#    Guard: the screeners and routing must not import or read any schwab/level2/volume_sweep symbol.
SCREENER_FILES = ["prime_setups", "watchlist_setups", "trade_ai_orchestrator", "atm_auto_approver"]
leak = []
for stem in SCREENER_FILES:
    for f in SCRIPTS.glob(f"*{stem}*.py"):
        txt = f.read_text()
        if re.search(r"level\s*2|level_ii|levelii|volume_sweep|depth_of_book|nasdaq_book|nyse_book|schwab_position_sync|schwab_adapter", txt, re.I):
            leak.append(f.name)
ok("Level II / volume / Schwab data isolated from screeners+routing (Rule 9)", not leak, f"leak: {leak}" if leak else "no references")

passed = sum(1 for _, p, _ in checks if p)
print(f"\n  {passed}/{len(checks)} guards green")
sys.exit(0 if passed == len(checks) else 1)
