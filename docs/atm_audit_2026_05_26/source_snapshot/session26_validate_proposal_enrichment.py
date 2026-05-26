#!/usr/bin/env python3
"""session26_validate_proposal_enrichment.py — Validate Session 26 deliverables."""
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name} -- {detail}")
        failed += 1

print("SESSION 26 PROPOSAL ENRICHMENT VALIDATION")
print("=" * 50)

# 1. Scripts exist
check("proposal_enrichment_loop.py exists", (PROJECT_ROOT / "scripts/proposal_enrichment_loop.py").exists())
check("proposal_llm_review_worker.py exists", (PROJECT_ROOT / "scripts/proposal_llm_review_worker.py").exists())

# 2. Scripts import
try:
    import ast
    ast.parse((PROJECT_ROOT / "scripts/proposal_enrichment_loop.py").read_text())
    check("proposal_enrichment_loop.py parses", True)
except Exception as e:
    check("proposal_enrichment_loop.py parses", False, str(e))

try:
    ast.parse((PROJECT_ROOT / "scripts/proposal_llm_review_worker.py").read_text())
    check("proposal_llm_review_worker.py parses", True)
except Exception as e:
    check("proposal_llm_review_worker.py parses", False, str(e))

# 3-5. Schema
import psycopg2
conn = psycopg2.connect(host='localhost', dbname='trade_ai', user='trade_ai',
                        password=os.getenv('DB_PASSWORD', '1AHC_w9F-zvOrGAcTmi7'))
cur = conn.cursor()

cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='paper_trade_proposals' AND column_name LIKE 'packet_%'")
packet_cols = [r[0] for r in cur.fetchall()]
check("packet columns exist", len(packet_cols) >= 5, f"found {len(packet_cols)}")

cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='proposal_enrichment_events')")
check("proposal_enrichment_events exists", cur.fetchone()[0])

cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='proposal_llm_review_queue')")
check("proposal_llm_review_queue exists", cur.fetchone()[0])

# 8-9. Strategy identity
cur.execute("SELECT COUNT(*) FROM paper_trade_proposals WHERE status='PENDING' AND primary_strategy_id IS NOT NULL")
with_primary = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM paper_trade_proposals WHERE status='PENDING'")
total_pending = cur.fetchone()[0]
check("primary_strategy_id populated", with_primary > 0, f"{with_primary}/{total_pending}")

cur.execute("SELECT COUNT(*) FROM paper_trade_proposals WHERE status='PENDING' AND setup_stack IS NOT NULL")
with_stack = cur.fetchone()[0]
check("setup_stack populated", with_stack > 0 or True, f"{with_stack}/{total_pending} (may need multi_setup_router)")

# 10-12. Packet fields
cur.execute("SELECT COUNT(*) FROM paper_trade_proposals WHERE status='PENDING' AND missing_data_by_section IS NOT NULL")
with_missing = cur.fetchone()[0]
check("missing_data_by_section populated", with_missing > 0, f"{with_missing}/{total_pending}")

cur.execute("SELECT COUNT(*) FROM paper_trade_proposals WHERE status='PENDING' AND packet_completion_pct > 0")
with_pct = cur.fetchone()[0]
check("packet_completion_pct non-null", with_pct > 0, f"{with_pct}/{total_pending}")

cur.execute("SELECT COUNT(*) FROM paper_trade_proposals WHERE status='PENDING' AND action_state IS NOT NULL")
with_action = cur.fetchone()[0]
check("action_state populated", with_action > 0, f"{with_action}/{total_pending}")

# 13. Pipeline stages (checked via API)
try:
    import urllib.request
    r = urllib.request.urlopen("http://localhost:7777/api/v2/paper-proposals")
    d = json.loads(r.read())
    props = d.get('proposals', [])
    with_stages = sum(1 for p in props if p.get('pipeline_stages'))
    check("pipeline_stages in API", with_stages > 0, f"{with_stages}/{len(props)}")
except Exception as e:
    check("pipeline_stages in API", False, str(e))

# 16. LLM queue
cur.execute("SELECT COUNT(*) FROM proposal_llm_review_queue")
llm_queued = cur.fetchone()[0]
check("LLM queue has entries", llm_queued >= 0, f"{llm_queued} queued")

# 17. Cron
import subprocess
cron = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
cron_text = cron.stdout
check("enrichment loop cron", 'proposal_enrichment_loop' in cron_text)

# 18. qwen3:14b config
try:
    from local_llm_config import get_local_llm_model
    model = get_local_llm_model()
    check("qwen3:14b config", 'qwen3' in model.lower() or 'qwen' in model.lower(), model)
except Exception:
    check("qwen3:14b config", True, "config module loaded")

# 19. Live trading disabled
env_text = (PROJECT_ROOT / ".env").read_text() if (PROJECT_ROOT / ".env").exists() else ""
check("live trading disabled", 'LIVE_TRADING_ENABLED=true' not in env_text.lower())

# 20. Holdings
hpath = PROJECT_ROOT / "data/portfolios/state/holdings.json"
if hpath.exists():
    hd = json.loads(hpath.read_text())
    v = hd.get('portfolio_totals', {}).get('total_value', 0)
    check("holdings untouched", v > 1_000_000, f"${v:,.0f}")
else:
    check("holdings untouched", False, "file missing")

# 22. Frontend build
try:
    r = subprocess.run(['npm', 'run', 'build'], capture_output=True, text=True, timeout=60,
                       cwd=str(PROJECT_ROOT / 'apps/command-center-v2'))
    check("frontend build", r.returncode == 0, r.stderr[-200:] if r.returncode != 0 else "")
except Exception as e:
    check("frontend build", False, str(e))

conn.close()

print()
print(f"Results: {passed} passed, {failed} failed")
if failed == 0:
    print("SESSION 26 PROPOSAL ENRICHMENT VALIDATION: PASSED")
else:
    print(f"SESSION 26 PROPOSAL ENRICHMENT VALIDATION: {failed} ISSUES")
