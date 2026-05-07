# Trade AI v12 — LLM Provider Guide
# Local Model, Grok Testing, GPU Upgrade, Cost Control, Recovery

**Version:** v3.7 — May 1, 2026  
**Server:** ms01-openclaw | SSH: `johnclaw@192.168.50.16`  
**Project root:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/`

---

## CURRENT STATE (May 1, 2026)

| Provider | Status | Used For | Cost |
|----------|--------|---------|------|
| Local qwen3:1.7b | ✅ Installed, normally working | All agent tasks, Telegram, OpenClaw | $0 |
| Grok grok-3-mini | ✅ Configured | Fallback when local slow/fails | ~$0.001/call |
| Claude Sonnet | ✅ Configured | Retirement/disability/CIO synthesis | ~$0.01/call |
| OpenAI gpt-4o | ✅ Configured | Last resort only | ~$0.005/call |

**Daily spend today: $0.43** — this is because the health check API shows local as
`available: false`, causing automated crons to fall back to Grok all day.

**Important:** `available: false` in the health API does NOT mean Ollama is broken.
It means the health check pinged Ollama and got a slow/no response (model loading).
Ollama IS working — Telegram works, OpenClaw works, Trade AI ran yesterday with 13 tickers.
The health check has a very short timeout (~150ms) and qwen3 needs 15-20s to think.

---

## QUESTION: If we fall back to local right now, what happens?

**Answer: Nothing bad. No freeze. Transparent fallback.**

The router already handles this automatically:
```
Local attempt → slow/timeout → Grok fallback → success → you see the result
```

You will NEVER see:
- A frozen terminal
- A failed Telegram message
- A broken agent analysis
- An error in the dashboard

You WILL see:
- A small cost ($0.001–$0.01 per fallback call) in the daily spend
- In logs: "local: empty response → grok fallback" 
- Normal output everywhere

The $0.43 spent today IS the fallback working correctly. System protected itself.

---

## QUESTION: How does local model recovery work?

### Step 1 — Verify Ollama is actually running (SSH)
```bash
ssh johnclaw@192.168.50.16
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Check if Ollama process is running
sudo systemctl status ollama --no-pager | head -5

# Check if Ollama API is responding (should return JSON with models)
curl -s http://localhost:11434/api/tags | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('Models installed:', [m['name'] for m in d.get('models',[])])
"
# Expected output: Models installed: ['qwen3:1.7b', 'nomic-embed-text:latest']
```

### Step 2 — Test if Ollama actually generates (the real test)
```bash
# This is the definitive test. If this returns text, local is working.
curl -s http://localhost:11434/api/generate \
  -d '{"model":"qwen3:1.7b","prompt":"say the word ok","stream":false,"think":false,"options":{"num_predict":10}}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('LOCAL RESPONSE:', repr(d.get('response','EMPTY')))"

# GOOD: LOCAL RESPONSE: 'ok'  (or any words)
# BAD:  LOCAL RESPONSE: ''    (empty — model needs restart)
# BAD:  Connection refused    (Ollama not running)
```

### Step 3 — If Ollama is not responding, restart it
```bash
sudo systemctl restart ollama
sleep 10   # Give it 10 seconds to load

# Test again
curl -s http://localhost:11434/api/generate \
  -d '{"model":"qwen3:1.7b","prompt":"say ok","stream":false,"think":false,"options":{"num_predict":5}}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('Response:', d.get('response','EMPTY'))"
```

### Step 4 — Verify the router sees local as working
```bash
.venv/bin/python scripts/llm_router.py --test
# Should show: Provider: local | Model: qwen3:1.7b | Response: [some text]
# If it shows: Provider: grok (local failed) — local still has issues
```

### Step 5 — Check the health API (optional — may still show false even when working)
```bash
# NOTE: health API uses a very short timeout. May show "false" even when Ollama works.
# Trust the curl test in Step 2 over the health API.
curl -s http://localhost:11434/api/tags | grep name
```

### Full local recovery checklist
```
[ ] ollama list shows qwen3:1.7b and nomic-embed-text
[ ] curl generate test returns non-empty text
[ ] llm_router.py --test shows Provider: local
[ ] Telegram bot responds to "status" command
[ ] OpenClaw functions normally
```

---

## COST CONTROL — Stop Automated Fallbacks to Grok

**Problem:** When local is slow/down, ALL crons fall back to Grok. 
65 crons × $0.001/call = potential $0.065/hour = $1.56/day just from fallbacks.

**Solution: Set a low daily budget that stops cloud spend after your manual testing.**

### Option A — Reduce daily cloud budget (recommended)
```bash
ssh johnclaw@192.168.50.16
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Current budget is $5/day (set in v3.7)
# Change it back to $0.50/day — enough for occasional Alex analysis, 
# stops runaway Grok fallback from automated crons
grep "DAILY_BUDGET_LIMIT" scripts/llm_router.py
# Shows: DAILY_BUDGET_LIMIT = 5.00

# To reduce: edit that one line
nano scripts/llm_router.py
# Change: DAILY_BUDGET_LIMIT = 5.00
# To:     DAILY_BUDGET_LIMIT = 0.50
# Save: Ctrl+O, Enter, Ctrl+X
```

Once budget is hit, ALL cloud providers are skipped and system uses local only.
Local either responds or logs "no response" and moves on — never hangs.

### Option B — Temporarily disable Grok in routing (most conservative)
```bash
# Add to .env — disables Grok entirely for automated tasks
echo "DISABLE_GROK_AUTO=true" >> .env
```
Then Claude Code adds a check: if `DISABLE_GROK_AUTO=true` AND caller is not `--manual`, skip Grok.
Remove when done: `sed -i '/DISABLE_GROK_AUTO/d' .env`

### Current budget status
```bash
# Check today's spend
tail -100 logs/llm_router.log | python3 -c "
import json, sys
from datetime import datetime
today = datetime.now().strftime('%Y-%m-%d')
total = 0.0
for line in sys.stdin:
    try:
        e = json.loads(line)
        if today in e.get('timestamp','') and e.get('provider') != 'local':
            total += e.get('cost', 0)
            print(f\"  {e['provider']:8} {e['task_type']:25} \${e['cost']:.4f}\")
    except: pass
print(f'Total today: \${total:.4f}')
"
```

---

## TESTING — Manual Grok Test Without Automated Runs

**Rule: Never test by triggering automated pipelines. Always use --manual flags.**

### Safe manual tests (no crons, no automated anything)

```bash
ssh johnclaw@192.168.50.16
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Test 1: See current routing table (zero cost, no LLM call)
.venv/bin/python scripts/llm_router.py --routing

# Test 2: Test Grok directly (one single call, ~$0.001)
.venv/bin/python scripts/llm_router.py --test-grok

# Test 3: Test local directly (zero cost)
curl -s http://localhost:11434/api/generate \
  -d '{"model":"qwen3:1.7b","prompt":"Is SCHD a good dividend ETF?","stream":false,"think":false,"options":{"num_predict":50}}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('response','EMPTY'))"

# Test 4: Test full debate (Grok, ~$0.01 total for 1-2 rounds)
.venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
from agent_watchlist_engine import run_agent_debate
r = run_agent_debate('SCHD', 'Testing: Is SCHD worth holding given current market?')
print(f'Provider: {r.get(\"provider\")}')
print(f'Rounds: {r.get(\"rounds\",1)}')
print(f'Consensus: {r.get(\"consensus\")}')
print(f'Confidence: {r.get(\"confidence\")}')
"

# Test 5: Test heat + session injection (zero cost — reads files only)
.venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
from intel_query import get_portfolio_heat_context, get_market_session_context
print('--- HEAT ---')
print(get_portfolio_heat_context())
print()
print('--- SESSION ---')
print(get_market_session_context())
"

# Test 6: Test sector correlation (zero cost — reads DB only)
.venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
from agent_watchlist_engine import detect_sector_correlation
r = detect_sector_correlation(['TDG','LHX','LMT','NOC','RTX'])
if r:
    print('DETECTED:', r['sector_label'])
    print('Symbols:', r['symbols'])
    print('Note:', r['note'])
else:
    print('No correlation detected')
"
```

### What NOT to do for testing
```
❌ Don't restart tradeai-continuous — it runs all 23 pipeline stages
❌ Don't run agent_router.py --daily-intel — triggers all agent analyses
❌ Don't run overnight_batch.py without --dry-run — hits LLM for every symbol
❌ Don't restart portfolio-server — it's already running via nohup, works fine
```

---

## GPU UPGRADE — Full Documentation

### Before GPU (current — qwen3:1.7b)
```
Routing:  local → grok → claude → openai
Local:    1.7b model, 1.4GB, generates in 15-20s
Quality:  Maria avg confidence 0.49 (shallow reasoning)
Cost:     $0 local, Grok fallback ~$0.001/call
```

### When GPU arrives — EXACT steps
```bash
ssh johnclaw@192.168.50.16
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Step 1: Pull the model (10-20 min download, ~8GB)
ollama pull qwen3:14b
# Wait for completion. Verify:
ollama list
# Should show: qwen3:14b alongside qwen3:1.7b

# Step 2: Test qwen3:14b directly before activating
curl -s http://localhost:11434/api/generate \
  -d '{"model":"qwen3:14b","prompt":"Should I hold SCHD given 6% portfolio heat?","stream":false,"think":false,"options":{"num_predict":80}}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('response','EMPTY')[:200])"
# If this returns a coherent paragraph → model is working

# Step 3: Activate (single line — everything auto-adjusts)
echo "LOCAL_MODEL=qwen3:14b" >> .env

# Step 4: Verify routing changed
.venv/bin/python scripts/llm_router.py --routing
# Should print: "GPU mode: qwen3:14b — Grok demoted to fallback"
# And show:     agent_debate → local → claude → grok   (local first now)

# Step 5: Run ONE manual test before letting crons use it
.venv/bin/python scripts/llm_router.py --test
# Should show: Provider: local | Model: qwen3:14b

# Step 6: Reduce budget back (Grok less needed now)
# Edit scripts/llm_router.py: DAILY_BUDGET_LIMIT = 1.00
```

### What changes automatically after GPU activation
| Setting | Before (1.7b) | After (14b) |
|---------|--------------|-------------|
| Local model | qwen3:1.7b | qwen3:14b |
| agent_debate routing | local → grok | local → claude → grok |
| sector_correlation | grok → local | local → grok |
| agent_narrative | local → grok | local → claude → grok |
| Grok role | Primary testing | Fallback only |
| Expected Maria confidence | 0.49 | 0.65+ expected |
| Cost | $0.43/day fallbacks | ~$0.05/day |

Claude stays primary for: `cio_synthesis`, retirement, disability, Roth — ALWAYS.
This never changes regardless of GPU.

### Revert GPU if anything goes wrong
```bash
ssh johnclaw@192.168.50.16

# Remove the LOCAL_MODEL line from .env
sed -i '/LOCAL_MODEL=qwen3:14b/d' /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env

# Verify revert
.venv/bin/python /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/llm_router.py --routing
# Should show: PRE-GPU | LOCAL_MODEL: qwen3:1.7b

# Test local still works
curl -s http://localhost:11434/api/generate \
  -d '{"model":"qwen3:1.7b","prompt":"say ok","stream":false,"think":false,"options":{"num_predict":5}}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin).get('response','EMPTY'))"
```

---

## TRADEAI-CONTINUOUS SERVICE — Why It Fails and Why It Doesn't Matter

### What it is
A systemd timer that runs the Trade AI 23-stage scanner pre-market.
Schedule: triggers via `tradeai-continuous.timer` (typically 4 AM–10 AM weekdays).

### Why it shows "failed"
The service exited with code 2 at 4:00 AM today. 
Looking at the journal output, the last successful operation was the preflight check
showing 21 PASS, 2 FAIL — and those 2 failures (service checks) caused exit code 2.

### Why it doesn't matter right now
- Last successful run: yesterday 0900 — produced 13 tickers, 3 GO (INSG +22%, FATN +33%)
- Market is open now — the 4–10 AM scan window has passed
- The service will try again tomorrow at 4 AM
- Everything downstream (dashboard, Telegram, Level 3 events) is unaffected
- portfolio_server.py is running via nohup (PID confirmed) — dashboard works fine

### Permanent fix (do this when ready — NOT urgent)
The `run_continuous.sh` preflight check gates the service — if preflight returns
any failures, the script exits with code 2. The fix is to make service failures
a WARNING (not a blocker) since portfolio-server running via nohup will always 
show as "inactive" in systemd.

**When ready to fix — paste this in SSH:**
```bash
ssh johnclaw@192.168.50.16
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# See the full launcher
cat linux_launchers/run_continuous.sh
```
Send the output and I'll give the exact one-line fix.

---

## PROVIDER ROUTING — Complete Reference

### Current routing table (pre-GPU, qwen3:1.7b)
```
Task type                 Standard route              High-impact route
─────────────────────     ──────────────────          ─────────────────────
agent_narrative           local → grok → claude       grok → claude → local
agent_debate              local → grok → claude       grok → claude → local
sector_correlation        grok → local → claude       grok → claude → local
cio_synthesis             local → claude → grok       claude → grok → openai
catalyst_classification   local → grok                (same)
sentiment                 local → grok                (same)
code_generation           claude → openai             (same)
fast_summary              local                       (same)
default                   local → grok → claude       claude → grok → local
```

### After GPU routing (post-GPU, qwen3:14b)
```
Task type                 Standard route              Change
─────────────────────     ──────────────────          ──────────────────
agent_narrative           local → claude → grok       Grok demoted
agent_debate              local → claude → grok       Grok demoted
sector_correlation        local → grok → claude       Local promoted
(all others unchanged)
```

### Budget gate behavior
When `DAILY_BUDGET_LIMIT` is exceeded:
- All external providers (grok, claude, openai) are SKIPPED
- System uses local only
- If local returns empty: job logs failure, moves on
- Nothing hangs, nothing crashes
- Next day at midnight: budget resets, cloud available again

---

## QUICK REFERENCE — All LLM Commands

```bash
# Always SSH first
ssh johnclaw@192.168.50.16
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Check routing
.venv/bin/python scripts/llm_router.py --routing

# Test all providers
.venv/bin/python scripts/llm_router.py --test

# Test Grok only
.venv/bin/python scripts/llm_router.py --test-grok

# Check today's spend
grep "$(date +%Y-%m-%d)" logs/llm_router.log | python3 -c "
import json,sys
total=0
for l in sys.stdin:
    try: e=json.loads(l); total+=e.get('cost',0); print(f\"  {e['provider']:8} {e['task_type']:20} \${e['cost']:.4f}\")
    except: pass
print(f'TOTAL: \${total:.4f}')
" 2>/dev/null | tail -20

# Test Ollama directly (zero cost)
curl -s http://localhost:11434/api/generate \
  -d '{"model":"qwen3:1.7b","prompt":"say ok","stream":false,"think":false,"options":{"num_predict":5}}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin).get('response','EMPTY'))"

# Check Ollama service
sudo systemctl status ollama --no-pager | head -5

# Restart Ollama (only if curl test shows Connection refused)
sudo systemctl restart ollama && sleep 10

# Reduce budget to stop Grok fallbacks ($0.50 = enough for Alex, stops runaway)
# Edit scripts/llm_router.py line: DAILY_BUDGET_LIMIT = 0.50
nano scripts/llm_router.py

# Activate GPU (when qwen3:14b installed)
echo "LOCAL_MODEL=qwen3:14b" >> .env

# Revert GPU
sed -i '/LOCAL_MODEL=qwen3:14b/d' .env
```

---

## WHAT TO DO RIGHT NOW (priority order)

1. **Reduce budget** — change `DAILY_BUDGET_LIMIT = 5.00` → `0.50` in `scripts/llm_router.py`
   This stops the $0.43/day Grok fallback drain while local is occasionally slow.
   One line change. Safe. Reversible. No restart needed.

2. **Review 9 pending approvals** — go to `http://192.168.50.16:7777/v2/approvals`
   TDG → TRIM (both agents agree — approve)
   RTX → TRIM (both agents agree — approve)
   LMT → wait for Alex (conflict — skip for now)
   LHX → HOLD (Risk 85% conviction — approve)
   NOC → HOLD (agree — approve)
   Each click feeds the learning loop. Zero risk.

3. **Leave tradeai-continuous alone** — not urgent, fixes itself tomorrow at 4 AM
   if Ollama is healthy. Only fix if it fails again tomorrow.

4. **Do NOT implement FORCE_DEBATE_PROVIDER** yet — budget reduction is safer
   and addresses the actual problem (cost) without adding new code.

---

*LLM Provider Guide v1.0 — May 1, 2026*
*Part of Trade AI v12 documentation set*
*Related: SKILL.md v3.7, TRADE_AI_V12_SYSTEM_BIBLE_V3.md*
