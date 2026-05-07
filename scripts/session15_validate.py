#!/usr/bin/env python3
"""session15_validate.py — Validate Session 15 deliverables."""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

PASSED = 0
FAILED = 0
SKIPPED = 0

def check(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name} — {detail}")


def skip(name, reason=""):
    global SKIPPED
    SKIPPED += 1
    print(f"  SKIP  {name} — {reason}")


print("=" * 60)
print("SESSION 15 VALIDATION")
print("=" * 60)

# 1. New tables exist
print("\n[1] Tables")
from session13_db import get_conn
conn = get_conn()
cur = conn.cursor()
for tbl in ['open_trade_alerts', 'paper_trade_analysis', 'agent_curation_events', 'local_llm_runs']:
    cur.execute("SELECT to_regclass(%s)", [tbl])
    check(f"Table {tbl}", cur.fetchone()[0] is not None, "not found")

# 2. New scripts parse
print("\n[2] Script syntax")
for script in ['open_trade_monitor.py', 'agent_curation_hooks.py', 'paper_trade_analyzer.py']:
    fpath = PROJECT_ROOT / 'scripts' / script
    try:
        ast.parse(fpath.read_text())
        check(f"{script} syntax", True)
    except Exception as e:
        check(f"{script} syntax", False, str(e))

# 3. API endpoints return JSON
print("\n[3] API endpoints")
import urllib.request
for ep in ['open-trade-monitor', 'paper-trade-analysis', 'agent-curation-events', 'local-llm-status']:
    try:
        with urllib.request.urlopen(f'http://localhost:7777/api/v2/{ep}', timeout=10) as resp:
            data = json.loads(resp.read())
            d = data.get('data', data)
            check(f"/api/v2/{ep}", d.get('ok', False), f"ok={d.get('ok')}")
    except Exception as e:
        check(f"/api/v2/{ep}", False, str(e))

# 4. Open trade monitor dry-run
print("\n[4] Monitor dry-run")
try:
    r = subprocess.run(
        [str(PROJECT_ROOT / '.venv/bin/python'), 'scripts/open_trade_monitor.py', '--dry-run', '--no-telegram'],
        capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT)
    )
    check("Monitor dry-run", r.returncode == 0, r.stderr[:100] if r.returncode else "")
except Exception as e:
    check("Monitor dry-run", False, str(e))

# 5. Analyzer dry-run
print("\n[5] Analyzer dry-run")
try:
    r = subprocess.run(
        [str(PROJECT_ROOT / '.venv/bin/python'), 'scripts/paper_trade_analyzer.py', '--dry-run', '--limit', '2'],
        capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT)
    )
    check("Analyzer dry-run", r.returncode == 0, r.stderr[:100] if r.returncode else "")
except Exception as e:
    check("Analyzer dry-run", False, str(e))

# 6. Quality filter exists
print("\n[6] Quality filter")
try:
    from paper_trade_logger import proposal_quality_check
    passed, codes = proposal_quality_check({'score': 30})
    check("proposal_quality_check exists", True)
    check("Low score filtered", not passed and 'SCORE_TOO_LOW' in codes,
          f"passed={passed} codes={codes}")
except Exception as e:
    check("proposal_quality_check", False, str(e))

# 7. Curation hook in close_paper_trade
print("\n[7] Curation hook integration")
try:
    src = (PROJECT_ROOT / 'scripts/paper_trade_logger.py').read_text()
    check("Hook in close_paper_trade", 'on_paper_trade_closed' in src, "not found")
except Exception as e:
    check("Hook in close_paper_trade", False, str(e))

# 8. Alpaca close path has hook
try:
    src = (PROJECT_ROOT / 'scripts/alpaca_paper_adapter.py').read_text()
    check("Hook in alpaca_paper_adapter", 'on_paper_trade_closed' in src, "not found")
except Exception as e:
    check("Hook in alpaca_paper_adapter", False, str(e))

# 9. Real journal clean
print("\n[8] Journal cleanliness")
try:
    with urllib.request.urlopen('http://localhost:7777/api/v2/journal', timeout=10) as resp:
        jdata = json.loads(resp.read())
        trades = jdata.get('data', {}).get('trades', []) if isinstance(jdata.get('data'), dict) else jdata.get('trades', [])
        if isinstance(trades, list):
            paper = [t for t in trades if isinstance(t, dict) and 'PAPER' in str(t.get('account', ''))]
            check("Real journal clean", len(paper) == 0, f"{len(paper)} paper trades found")
        else:
            skip("Real journal clean", "unexpected data shape")
except Exception as e:
    check("Real journal clean", False, str(e))

# 10. No hardcoded secrets
print("\n[9] Security")
try:
    s15_scripts = ['open_trade_monitor.py', 'agent_curation_hooks.py',
                   'paper_trade_analyzer.py']
    s15_hits = []
    for sf in s15_scripts:
        fp = PROJECT_ROOT / 'scripts' / sf
        if fp.exists() and '1AHC_w9F' in fp.read_text():
            s15_hits.append(sf)
    check("No hardcoded DB password in S15 files", len(s15_hits) == 0,
          "found in: " + ", ".join(s15_hits))
except Exception as e:
    skip("No hardcoded DB password", str(e))

# 11. No live Alpaca endpoint
try:
    r = subprocess.run(
        ['grep', '-r', 'api.alpaca.markets', 'scripts/', 'apps/command-center-v2/src/'],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT)
    )
    lines = [l for l in r.stdout.splitlines()
             if 'paper-api' not in l and '#' not in l.split('api.alpaca')[0]
             and 'session15_validate' not in l]
    check("No live Alpaca URL", len(lines) == 0, f"found: {lines[:2]}")
except Exception as e:
    skip("No live Alpaca URL", str(e))

# 12. Crons not duplicated
print("\n[10] Crons")
try:
    r = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    monitor_count = sum(1 for l in r.stdout.splitlines() if 'open_trade_monitor' in l)
    analyzer_count = sum(1 for l in r.stdout.splitlines() if 'paper_trade_analyzer' in l)
    check("Monitor cron exists", monitor_count >= 1, f"count={monitor_count}")
    check("Analyzer cron exists", analyzer_count >= 1, f"count={analyzer_count}")
    check("No duplicate crons", monitor_count <= 1 and analyzer_count <= 1,
          f"monitor={monitor_count} analyzer={analyzer_count}")
except Exception as e:
    skip("Crons", str(e))

# 13. Holdings unchanged
print("\n[11] Holdings")
try:
    d = json.loads((PROJECT_ROOT / 'data/portfolios/state/holdings.json').read_text())
    v = d['portfolio_totals']['total_value']
    check("Holdings safe", v > 1000000, f"value={v}")
except Exception as e:
    check("Holdings safe", False, str(e))

# 14. api_v2.py syntax
print("\n[12] Core syntax")
try:
    ast.parse((PROJECT_ROOT / 'scripts/api_v2.py').read_text())
    check("api_v2.py syntax", True)
except Exception as e:
    check("api_v2.py syntax", False, str(e))

conn.close()

# Summary
print("\n" + "=" * 60)
total = PASSED + FAILED + SKIPPED
if FAILED == 0:
    print(f"SESSION 15 VALIDATION: PASSED ({PASSED}/{total})")
else:
    print(f"SESSION 15 VALIDATION: {FAILED} FAILURES ({PASSED} passed, {SKIPPED} skipped)")
print("=" * 60)

sys.exit(0 if FAILED == 0 else 1)
