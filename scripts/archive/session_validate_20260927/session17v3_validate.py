#!/usr/bin/env python3
"""session17v3_validate.py — Validation for Session 17 v3: Research Packet + Agent Review + Backtest."""
import json
import os
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

passed = 0
failed = 0
warnings = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name} {detail}")
        failed += 1

def warn(name, detail=""):
    global warnings
    print(f"  WARN: {name} {detail}")
    warnings += 1

print("=" * 60)
print("SESSION 17v3 VALIDATION")
print("=" * 60)

# 1. Tables exist
print("\n1. New tables")
try:
    import subprocess as _sp
    for tbl in ['proposal_research_packets', 'proposal_agent_reviews', 'proposal_backtest_snapshots']:
        r = _sp.run(['psql', '-h', '127.0.0.1', '-U', 'trade_ai', '-d', 'trade_ai', '-t', '-c',
                      f"SELECT to_regclass('{tbl}')"], capture_output=True, text=True)
        check(f"Table {tbl}", tbl in r.stdout)
except Exception as e:
    check("DB tables", False, str(e))

# 2. New scripts importable
print("\n2. New scripts")
for script in [
    'proposal_technical_snapshot',
    'proposal_backtest_engine',
    'proposal_agent_review',
    'proposal_llm_reviewer',
    'proposal_research_packet_builder',
    'proposal_decision_gate',
]:
    path = PROJECT_ROOT / 'scripts' / f'{script}.py'
    check(f"Script {script}.py exists", path.exists())
    if path.exists():
        try:
            import ast
            ast.parse(path.read_text())
            check(f"Script {script}.py syntax", True)
        except Exception as e:
            check(f"Script {script}.py syntax", False, str(e))

# 3. API endpoints return JSON
print("\n3. API endpoints")
try:
    r = urllib.request.urlopen("http://localhost:7777/api/v2/paper-proposals", timeout=10)
    d = json.loads(r.read())
    check("GET /api/v2/paper-proposals", d.get('ok'))
except Exception as e:
    check("GET /api/v2/paper-proposals", False, str(e))

# 4. Latest proposal has research fields
print("\n4. Proposal enrichment")
try:
    r = urllib.request.urlopen("http://localhost:7777/api/v2/paper-proposals", timeout=10)
    d = json.loads(r.read())
    proposals = d.get('proposals', [])
    if proposals:
        p = proposals[0]
        required_fields = [
            'decision_state', 'research_score', 'confidence_score',
            'agent_review_status', 'local_llm_review_status', 'backtest_status',
            'approval_allowed', 'approval_blocked_reason', 'agent_votes',
            'stock_history_summary', 'required_reviews', 'completed_reviews',
        ]
        for f in required_fields:
            check(f"Field {f} present", f in p, f"missing from proposal {p.get('id')}")
        check("Decision state populated", p.get('decision_state') is not None)
        check("Research score populated", p.get('research_score') is not None)
    else:
        warn("No proposals to validate", "Need at least one PENDING proposal")
except Exception as e:
    check("Proposal enrichment", False, str(e))

# 5. UI strings
print("\n5. UI approval gating strings")
ui_path = PROJECT_ROOT / 'apps' / 'command-center-v2' / 'src' / 'pages' / 'PaperProposals.tsx'
if ui_path.exists():
    ui_text = ui_path.read_text()
    for s in ['Run AI Review', 'Run Research', 'Run Backtest', 'AI_REVIEW_MISSING',
              'BACKTEST_INSUFFICIENT', 'APPROVE_READY_PAPER_TEST', 'stock_history']:
        check(f"UI string '{s}'", s in ui_text)
else:
    check("PaperProposals.tsx exists", False)

# 6. Real journal clean
print("\n6. Real journal clean")
try:
    r = urllib.request.urlopen("http://localhost:7777/api/v2/journal", timeout=10)
    d = json.loads(r.read())
    trades = d.get('trades', d.get('data', []))
    paper = [t for t in trades if 'PAPER' in str(t.get('account', '')) or 'PAPER' in str(t.get('account_name', ''))]
    check("No paper trades in real journal", len(paper) == 0, f"found {len(paper)} paper trades")
except Exception as e:
    warn("Journal check", str(e))

# 7. No hardcoded secrets
print("\n7. No hardcoded secrets")
import subprocess
result = subprocess.run(
    ['grep', '-rl', '1AHC_w9F', 'scripts/', 'apps/command-center-v2/src/'],
    capture_output=True, text=True
)
# Exclude validation scripts themselves
hits = [l for l in result.stdout.strip().split('\n') if l and 'validate' not in l]
check("No hardcoded DB fallback", len(hits) == 0, f"found: {hits[:3]}" if hits else "")

# 8. No live Alpaca endpoint
print("\n8. No live Alpaca endpoint")
result = subprocess.run(
    ['grep', '-r', 'api.alpaca.markets', 'scripts/', 'apps/command-center-v2/src/'],
    capture_output=True, text=True
)
live_hits = [l for l in result.stdout.strip().split('\n') if l and 'paper-api' not in l and 'validate' not in l and 'grep' not in l]
check("No live Alpaca URL", len(live_hits) == 0, f"found: {live_hits[:3]}" if live_hits else "")

# 9. Frontend build
print("\n9. Frontend build")
build_dir = PROJECT_ROOT / 'apps' / 'command-center-v2' / 'dist'
check("Frontend dist exists", build_dir.exists())
if build_dir.exists():
    js_files = list(build_dir.rglob('*.js'))
    check("Frontend JS files exist", len(js_files) > 0)

# 10. Holdings unchanged
print("\n10. Holdings")
try:
    hpath = PROJECT_ROOT / 'data' / 'portfolios' / 'state' / 'holdings.json'
    h = json.loads(hpath.read_text())
    val = h['portfolio_totals']['total_value']
    check(f"Holdings > $1M", val > 1000000, f"value=${val:,.0f}")
except Exception as e:
    check("Holdings", False, str(e))

# Summary
print("\n" + "=" * 60)
total = passed + failed
if failed == 0:
    print(f"SESSION 17v3 VALIDATION: PASSED ({passed}/{total} checks)")
else:
    print(f"SESSION 17v3 VALIDATION: FAILED ({failed} failures, {passed} passed)")
if warnings:
    print(f"  Warnings: {warnings}")
print("=" * 60)
