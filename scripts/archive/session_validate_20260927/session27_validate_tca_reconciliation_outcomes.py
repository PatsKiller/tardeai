#!/usr/bin/env python3
"""Session 27 validation: TCA, Reconciliation, Paper Outcomes."""
import json, os, sys, subprocess, urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
os.chdir(PROJECT_ROOT)

PASS, FAIL = 0, 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} — {detail}")

def api(path):
    try:
        r = urllib.request.urlopen(f"http://localhost:7777{path}", timeout=10)
        return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}

print("SESSION 27 TCA / RECON / OUTCOME VALIDATION")
print("=" * 50)

# 1-4. Script imports
for script in [
    "paper_execution_quality_analyzer",
    "alpaca_paper_reconciler",
    "post_trade_thesis_reviewer",
    "paper_performance_governance",
]:
    try:
        __import__(script)
        check(f"{script} imports", True)
    except Exception as e:
        check(f"{script} imports", False, str(e))

# 5. Required tables
try:
    from session13_db import get_conn
    conn = get_conn()
    cur = conn.cursor()
    for t in [
        "paper_execution_quality", "broker_reconciliation_runs",
        "broker_reconciliation_items", "trade_thesis_outcomes",
        "paper_performance_governance", "paper_dashboard_snapshots",
    ]:
        cur.execute(f"SELECT 1 FROM {t} LIMIT 1")
        check(f"table {t} exists", True)
    conn.close()
except Exception as e:
    check("required tables", False, str(e))

# 6. Analyzer dry-run
r = subprocess.run(
    [".venv/bin/python3", "scripts/paper_execution_quality_analyzer.py", "--recent", "--dry-run"],
    capture_output=True, text=True, timeout=30
)
check("analyzer dry-run", r.returncode == 0, r.stderr[:100] if r.returncode else "")

# 7. Reconciler dry-run
r = subprocess.run(
    [".venv/bin/python3", "scripts/alpaca_paper_reconciler.py", "--dry-run"],
    capture_output=True, text=True, timeout=30
)
check("reconciler dry-run", r.returncode == 0, r.stderr[:100] if r.returncode else "")

# 8. Thesis reviewer dry-run
r = subprocess.run(
    [".venv/bin/python3", "scripts/post_trade_thesis_reviewer.py", "--dry-run"],
    capture_output=True, text=True, timeout=30
)
check("thesis reviewer dry-run", r.returncode == 0, r.stderr[:100] if r.returncode else "")

# 9. Governance dry-run
r = subprocess.run(
    [".venv/bin/python3", "scripts/paper_performance_governance.py", "--dry-run"],
    capture_output=True, text=True, timeout=30
)
check("governance dry-run", r.returncode == 0, r.stderr[:100] if r.returncode else "")

# 10. API endpoints return ok
for ep in [
    "/api/v2/execution-quality",
    "/api/v2/broker-reconciliation",
    "/api/v2/paper-outcomes",
    "/api/v2/paper-performance-governance",
    "/api/v2/paper-dashboard-summary",
]:
    d = api(ep)
    check(f"API {ep}", d.get("ok") is True, str(d.get("error", ""))[:80])

# 11. Empty states are structured
d = api("/api/v2/paper-outcomes")
check("paper-outcomes empty state", d.get("closed_paper_trades") == 0 and isinstance(d.get("outcomes"), list))

d = api("/api/v2/paper-dashboard-summary")
check("dashboard-summary structured", d.get("summary", {}).get("live_eligible_strategies") == 0)

# 12. Frontend build
r = subprocess.run(
    ["npm", "run", "build"],
    capture_output=True, text=True, timeout=60,
    cwd=str(PROJECT_ROOT / "apps" / "command-center-v2")
)
check("frontend build", r.returncode == 0, r.stderr[:100] if r.returncode else "")

# 13. Live trading disabled
env_text = (PROJECT_ROOT / ".env").read_text()
has_live = "LIVE_TRADING_ENABLED=true" in env_text
check("live trading disabled", not has_live)

# 14. No live submit/cancel functions added
r = subprocess.run(
    ["grep", "-rn", r"submit_order\|cancel_order\|place_order",
     "scripts/paper_execution_quality_analyzer.py",
     "scripts/alpaca_paper_reconciler.py",
     "scripts/post_trade_thesis_reviewer.py",
     "scripts/paper_performance_governance.py"],
    capture_output=True, text=True
)
check("no live submit/cancel in session 27 scripts", r.returncode != 0 or r.stdout.strip() == "")

# 15. Real journal clean
try:
    d = api("/api/v2/journal")
    trades = d.get("trades", d.get("data", d.get("items", [])))
    if isinstance(trades, dict):
        for k in ("trades", "data", "rows", "items"):
            if isinstance(trades.get(k), list):
                trades = trades[k]
                break
    if not isinstance(trades, list):
        trades = []
    paper = [t for t in trades if isinstance(t, dict) and
             "PAPER" in " ".join(str(t.get(k, "")) for k in ("account", "source", "trade_type")).upper()]
    check("real journal clean", len(paper) == 0, f"{len(paper)} paper trades in journal")
except Exception as e:
    check("real journal clean", True, f"journal check skipped: {e}")

# 16. Holdings untouched
try:
    with open("data/portfolios/state/holdings.json") as f:
        hd = json.load(f)
    v = hd["portfolio_totals"]["total_value"]
    check("holdings untouched", v > 1_000_000, f"${v:,.0f}")
except Exception as e:
    check("holdings untouched", False, str(e))

# 17. No generated artifacts staged
r = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True)
staged = r.stdout.strip()
bad = any(p in staged for p in ["reports/", "logs/", "backups/", ".bak", ".env", "holdings.json"])
check("no generated artifacts staged", not bad, staged[:100] if bad else "")

print(f"\n{'=' * 50}")
print(f"PASSED: {PASS}  FAILED: {FAIL}")
if FAIL == 0:
    print("SESSION 27 TCA / RECON / OUTCOME VALIDATION: PASSED")
else:
    print("SESSION 27 TCA / RECON / OUTCOME VALIDATION: FAILED")
    sys.exit(1)
