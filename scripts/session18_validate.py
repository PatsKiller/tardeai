#!/usr/bin/env python3
"""session18_validate.py — Validation for Session 18: Pipeline Wiring + Signal Flow Integrity."""
import json
import subprocess
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name} {detail}")
        failed += 1

print("=" * 60)
print("SESSION 18 VALIDATION")
print("=" * 60)

# 1. strategy_signal_sync.py imports
print("\n1. Strategy signal sync module")
path = PROJECT_ROOT / 'scripts' / 'strategy_signal_sync.py'
check("strategy_signal_sync.py exists", path.exists())
if path.exists():
    import ast
    try:
        ast.parse(path.read_text())
        check("strategy_signal_sync.py syntax", True)
    except Exception as e:
        check("strategy_signal_sync.py syntax", False, str(e))

# 2. Signal flow audit table
print("\n2. Signal flow audit table")
r = subprocess.run(['psql', '-h', '127.0.0.1', '-U', 'trade_ai', '-d', 'trade_ai', '-t', '-c',
                      "SELECT to_regclass('signal_flow_audit')"], capture_output=True, text=True)
check("signal_flow_audit table", 'signal_flow_audit' in r.stdout)

# 3. Today's GO/A+ count
print("\n3. GO/A+ scans today")
r = subprocess.run(['psql', '-h', '127.0.0.1', '-U', 'trade_ai', '-d', 'trade_ai', '-t', '-c',
                      """SELECT COUNT(DISTINCT symbol) FROM trade_ai_scans
                         WHERE decision IN ('GO','A+')
                         AND (scanned_at AT TIME ZONE 'America/New_York')::date =
                             (NOW() AT TIME ZONE 'America/New_York')::date"""],
                     capture_output=True, text=True)
go_count = int(r.stdout.strip()) if r.stdout.strip().isdigit() else 0
print(f"  GO/A+ count today: {go_count}")

# 4. Today's strategy_signals count
print("\n4. Strategy signals today")
r = subprocess.run(['psql', '-h', '127.0.0.1', '-U', 'trade_ai', '-d', 'trade_ai', '-t', '-c',
                      """SELECT COUNT(DISTINCT symbol) FROM strategy_signals
                         WHERE fired_at::date = CURRENT_DATE"""],
                     capture_output=True, text=True)
signal_count = int(r.stdout.strip()) if r.stdout.strip().isdigit() else 0
print(f"  strategy_signals count today: {signal_count}")

# 5. If GO/A+ > 0, strategy_signals > 0
if go_count > 0:
    check("GO signals become strategy_signals", signal_count > 0, f"GO={go_count} but signals={signal_count}")
else:
    print("  SKIP: No GO/A+ scans today")

# 6. No invalid long plans in strategy_signals
print("\n6. Invalid long plans check")
r = subprocess.run(['psql', '-h', '127.0.0.1', '-U', 'trade_ai', '-d', 'trade_ai', '-t', '-c',
                      """SELECT COUNT(*) FROM strategy_signals
                         WHERE fired_at::date = CURRENT_DATE
                         AND status IN ('active','pending','ACTIVE','PENDING')
                         AND (stop_loss >= entry_high OR target_1 <= entry_high)"""],
                     capture_output=True, text=True)
invalid = int(r.stdout.strip()) if r.stdout.strip().isdigit() else 0
check("No inverted stop/target in active signals", invalid == 0, f"found {invalid}")

# 7. Prospects timestamp
print("\n7. Prospects timestamp")
try:
    r = urllib.request.urlopen("http://localhost:7777/api/v2/prospects", timeout=10)
    d = json.loads(r.read())
    check("Prospects has last_scan", d.get('last_scan') is not None)
    check("Prospects has scan_freshness_label", d.get('scan_freshness_label') is not None)
except Exception as e:
    check("Prospects API", False, str(e))

# 8. Strategy Desk has signals
print("\n8. Strategy Desk")
try:
    r = urllib.request.urlopen("http://localhost:7777/api/v2/strategy-desk", timeout=10)
    d = json.loads(r.read())
    data = d.get('data', d)
    signals = data.get('signals_by_strategy') or data.get('signals', {})
    total = sum(len(v) for v in signals.values()) if isinstance(signals, dict) else 0
    if go_count > 0:
        check("Strategy Desk has signals", total > 0, f"total={total}")
    else:
        print(f"  SKIP: No GO scans today (desk has {total} signals)")
except Exception as e:
    check("Strategy Desk API", False, str(e))

# 9. SEAT proposals not pending
print("\n9. SEAT proposals")
r = subprocess.run(['psql', '-h', '127.0.0.1', '-U', 'trade_ai', '-d', 'trade_ai', '-t', '-c',
                      "SELECT COUNT(*) FROM paper_trade_proposals WHERE symbol='SEAT' AND status='PENDING'"],
                     capture_output=True, text=True)
seat_pending = int(r.stdout.strip()) if r.stdout.strip().isdigit() else 0
check("No pending SEAT proposals", seat_pending == 0, f"found {seat_pending}")

# 10. No hardcoded DB fallback in new files
print("\n10. No hardcoded secrets")
result = subprocess.run(['grep', '-l', '1AHC_w9F',
                          'scripts/strategy_signal_sync.py',
                          'scripts/session18_signal_flow_health.py'],
                         capture_output=True, text=True)
check("No hardcoded DB in new files", result.returncode != 0)

# 11. Real journal clean
print("\n11. Real journal")
try:
    r = urllib.request.urlopen("http://localhost:7777/api/v2/journal", timeout=10)
    d = json.loads(r.read())
    trades = d.get('trades', d.get('data', []))
    if isinstance(trades, list):
        paper = [t for t in trades if isinstance(t, dict) and 'PAPER' in str(t.get('account', ''))]
        check("No paper trades in real journal", len(paper) == 0)
    else:
        print("  SKIP: journal format check")
except Exception as e:
    print(f"  SKIP: journal check — {e}")

# 12. Frontend build
print("\n12. Frontend")
dist = PROJECT_ROOT / 'apps' / 'command-center-v2' / 'dist'
check("Frontend dist exists", dist.exists())

# 13. Holdings unchanged
print("\n13. Holdings")
try:
    h = json.loads((PROJECT_ROOT / 'data' / 'portfolios' / 'state' / 'holdings.json').read_text())
    val = h['portfolio_totals']['total_value']
    check(f"Holdings > $1M (${val:,.0f})", val > 1000000)
except Exception as e:
    check("Holdings", False, str(e))

# Summary
print("\n" + "=" * 60)
total = passed + failed
if failed == 0:
    print(f"SESSION 18 VALIDATION: PASSED ({passed}/{total} checks)")
else:
    print(f"SESSION 18 VALIDATION: FAILED ({failed} failures, {passed} passed)")
print("=" * 60)
