---
name: trade-ai-v12
description: >
  Full-stack autonomous trading intelligence + retirement planning system running on
  ms01-openclaw (Ubuntu Linux). Use this skill when the user wants to: run any pipeline,
  check agent results, interpret GO/WAIT/NO GO tickers, debug cron jobs, work with
  PostgreSQL data, modify agent behavior, check portfolio health, run retirement analysis,
  review proposals, manage screeners, fix broken APIs, check credential status, understand
  agent decisions, build Level 3 autonomous features, deploy agent improvements, switch
  LLM providers, activate GPU upgrade, rollback changes, or anything related to the
  Trade AI v12 or Portfolio Intelligence v1.2 system.
  Also trigger on: "run trade ai", "check my agents", "what's moving", "check my portfolio",
  "why did the agent", "run the pipeline", "fix the cron", "check the DB", "what did Maria find",
  "show proposals", "run monthly", "event detector", "level 3", "autonomous", "deploy",
  "GPU upgrade", "Grok", "rollback", or any variation.
---

# Trade AI v12 + Portfolio Intelligence v1.2 — System Skill v3.7

**Server:** ms01-openclaw (Ubuntu Linux, NOT Windows)
**SSH:** `ssh johnclaw@192.168.50.16`
**Project root:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/`
**Dashboard (LAN):** `http://192.168.50.16:7777/v2`
**Database:** PostgreSQL — `trade_ai` — localhost:5432
**Docs folder:** `docs/project/` (SKILL.md, Bible, HTML reference all live here)

### Live System Stats (verified May 1, 2026 — preflight)
| Metric | Value |
|--------|-------|
| DB tables | **158** |
| News articles | **830** |
| Agent analyses | **1,652** |
| Active stops with real prices | **32** |
| Trade AI tickers (last run) | **13 tickers, 3 GO** |
| Cron entries | **65** |
| Services | tradeai-continuous + portfolio-server |

---

## CRITICAL — All Work Is Done Via SSH

```bash
# 1. Connect to server
ssh johnclaw@192.168.50.16

# 2. Always cd to project root first
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# 3. Use .venv/bin/python NOT python or python3
.venv/bin/python scripts/system_preflight_check.py
```

**Never use Windows paths, `python` without venv, or `.bat` launchers — this is Linux.**

---

## Agent Intelligence Improvements — v3.7 (Deployed May 1, 2026)

Five improvements deployed to 4 scripts. **Status: ✅ LIVE on server.**

| # | Improvement | File | Impact |
|---|------------|------|--------|
| #2 | Cross-agent reasoning in context | `intel_query.py` | Agents see WHY other agents said TRIM/HOLD, not just the label. Resolves LMT-style conflicts. |
| #4 | Portfolio heat in every prompt | `intel_query.py` | Live heat % + directive injected. At 6.2% → "bias toward stops over holds." |
| #6 | Market session context | `intel_query.py` | Pre-market/market-hours/after-hours/overnight — agents know whether to act or wait. |
| #5 | Sector correlation detection | `agent_watchlist_engine.py` + `agent_event_router.py` | 3+ stops same sector → SECTOR_CORRELATION_ALERT fires first. Maria investigates macro cause. |
| #3 | Counter-argument debate round | `agent_watchlist_engine.py` | Divergence >30% → Round 2 where agents respond to each other's arguments. ~$0.001 extra. |

### New Functions Added (intel_query.py)
- `get_market_session_context()` — PRE-MARKET/MARKET HOURS/AFTER-HOURS/OVERNIGHT string
- `get_portfolio_heat_context()` — reads `risk_management.json`, returns heat + directive
- `get_cross_agent_context(symbol, exclude_agent)` — other agents' verdict + reasoning from DB

### New Functions Added (agent_watchlist_engine.py)
- `detect_sector_correlation(symbols)` — returns alert dict if 3+ symbols share strategy/sector
- `insert_sector_correlation_event(correlation)` — inserts SECTOR_CORRELATION_ALERT into queue
- `get_symbol_strategy(symbol)` — looks up symbol's strategy from watchlist_strategy_cards
- `run_agent_debate()` — **replaced** with 2-round version (Round 2 when divergence > 30%)

### LLM Router Changes (llm_router.py)
- `grok-beta` → `grok-3-mini`
- Budget: `$2/day` → `$5/day`
- New task types: `agent_debate`, `sector_correlation`
- Two routing tables: `_TASK_ROUTING_PRE_GPU` (current) / `_TASK_ROUTING_POST_GPU` (after GPU)
- GPU switch: single `.env` line — see GPU section below

---

## Deploy v3.7 — Turnkey (Already Done — For Reference / Re-deploy)

### Step 1 — SCP zip to server (run on YOUR local machine, not SSH)

```powershell
# Windows PowerShell
scp C:\Users\john\Downloads\agent_improvements_v37.zip johnclaw@192.168.50.16:/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/
```

```bash
# Mac / Linux terminal
scp ~/Downloads/agent_improvements_v37.zip johnclaw@192.168.50.16:/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/
```

### Step 2 — SSH in
```bash
ssh johnclaw@192.168.50.16
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
```

### Step 3 — Extract, backup, deploy (paste entire block)
```bash
unzip -o agent_improvements_v37.zip -d /tmp/v37_deploy/ && \
cp scripts/intel_query.py scripts/intel_query.py.bak_v36 && \
cp scripts/agent_watchlist_engine.py scripts/agent_watchlist_engine.py.bak_v36 && \
cp scripts/agent_event_router.py scripts/agent_event_router.py.bak_v36 && \
cp scripts/llm_router.py scripts/llm_router.py.bak_v36 && \
cp /tmp/v37_deploy/intel_query_patched.py scripts/intel_query.py && \
cp /tmp/v37_deploy/agent_watchlist_engine_patched.py scripts/agent_watchlist_engine.py && \
cp /tmp/v37_deploy/agent_event_router_patched.py scripts/agent_event_router.py && \
cp /tmp/v37_deploy/llm_router_patched.py scripts/llm_router.py && \
echo "✅ Deployed"
```

### Step 4 — Verify syntax + routing
```bash
.venv/bin/python -c "
import ast
for f in ['scripts/intel_query.py','scripts/agent_watchlist_engine.py',
          'scripts/agent_event_router.py','scripts/llm_router.py']:
    ast.parse(open(f).read())
    print(f'  ✅ {f}')
"
.venv/bin/python scripts/llm_router.py --routing
.venv/bin/python scripts/system_preflight_check.py
```

### Step 5 — Test improvements (optional, costs ~$0.01 via Grok)
```bash
# Test heat + session injection
.venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
from intel_query import get_portfolio_heat_context, get_market_session_context
print(get_portfolio_heat_context())
print(get_market_session_context())
"

# Test sector correlation
.venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
from agent_watchlist_engine import detect_sector_correlation
r = detect_sector_correlation(['TDG','LHX','LMT','NOC','RTX'])
print(r['note'] if r else 'No correlation detected')
"

# Test 2-round debate (uses Grok ~$0.01)
.venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
from agent_watchlist_engine import run_agent_debate
r = run_agent_debate('LMT','Stop triggered — price below stop. Portfolio heat 6.2%.')
print(f'Rounds: {r.get(\"rounds\",1)} | Divergence: {r.get(\"divergence\",0)}% | Consensus: {r.get(\"consensus\")}')
"
```

---

## Rollback v3.7 → v3.6 (If Anything Goes Wrong)

```bash
# SSH in first
ssh johnclaw@192.168.50.16
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

cp scripts/intel_query.py.bak_v36 scripts/intel_query.py
cp scripts/agent_watchlist_engine.py.bak_v36 scripts/agent_watchlist_engine.py
cp scripts/agent_event_router.py.bak_v36 scripts/agent_event_router.py
cp scripts/llm_router.py.bak_v36 scripts/llm_router.py
echo "✅ Rolled back to v3.6"
.venv/bin/python scripts/system_preflight_check.py
```

---

## GPU Upgrade — Activate qwen3:14b (When Hardware Arrives)

### Install and activate (SSH)
```bash
ssh johnclaw@192.168.50.16
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Pull model (takes a few minutes)
ollama pull qwen3:14b

# Single-line activation — everything auto-adjusts in llm_router.py
echo "LOCAL_MODEL=qwen3:14b" >> .env

# Restart server to pick up .env change
sudo systemctl restart portfolio-server

# Verify — should print "GPU mode: qwen3:14b — Grok demoted to fallback"
.venv/bin/python scripts/llm_router.py --routing
```

### What changes automatically after GPU
| Before (qwen3:1.7b) | After (qwen3:14b) |
|--------------------|--------------------|
| Grok = primary cloud testing | Grok = fallback only |
| Local = low quality | Local = high quality |
| agent_debate → local → grok | agent_debate → local → claude |
| Budget $5/day cloud spend | Budget $5/day (mostly unused) |
| Maria avg confidence 0.49 | Expected: 0.65+ |

Claude always stays primary for `cio_synthesis`, retirement, disability — never replaced by local.

### Revert GPU if something fails
```bash
ssh johnclaw@192.168.50.16
# Edit .env and remove the LOCAL_MODEL=qwen3:14b line
sed -i '/LOCAL_MODEL=qwen3:14b/d' /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env
.venv/bin/python scripts/llm_router.py --routing
# Should show: PRE-GPU mode, Grok as primary
```

---

## Fix Service Failures (2 known issues)

Preflight shows 2 FAIL: `tradeai-continuous` and `portfolio-server`. These are common.

```bash
ssh johnclaw@192.168.50.16

# Check what failed
sudo systemctl status tradeai-continuous --no-pager -l | tail -20
ps aux | grep portfolio_server | grep -v grep

# Restart tradeai-continuous
sudo systemctl restart tradeai-continuous
sleep 3
sudo systemctl status tradeai-continuous --no-pager | head -5

# If portfolio-server running via nohup (check first)
ps aux | grep portfolio_server | grep -v grep
# If NOT running, start it:
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
nohup .venv/bin/python scripts/portfolio_server.py > logs/portfolio_server.log 2>&1 &
echo "Started portfolio-server via nohup PID $!"
```

**Note:** portfolio-server running via `nohup` instead of systemd is expected — preflight
always reports this as a SKIP/FAIL. System is fully functional when dashboard at
`http://192.168.50.16:7777/v2` is accessible.

---

## Quick Commands Reference

All commands require SSH first:
```bash
ssh johnclaw@192.168.50.16
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
```

### Health & Diagnostics
```bash
.venv/bin/python scripts/system_preflight_check.py          # 23-test check
.venv/bin/python scripts/llm_router.py --routing             # LLM chain
.venv/bin/python scripts/llm_router.py --test-grok           # Test Grok API
.venv/bin/python scripts/credential_monitor.py --check       # 10 credentials
.venv/bin/python scripts/agent_event_router.py --status      # Event queue
tail -50 logs/event_detector.log                             # Level 3 logs
tail -50 logs/event_router.log
tail -50 logs/llm_router.log                                 # LLM cost tracking
```

### Trade AI
```bash
# Test run — safe any time, no cost
.venv/bin/python scripts/trade_ai_orchestrator.py --run-label 0900 --skip-market-check --no-alerts --no-llm

# Standard run
.venv/bin/python scripts/trade_ai_orchestrator.py --run-label 0700
```

### Portfolio Intelligence
```bash
bash linux_launchers/run_portfolio.sh                        # Daily
rm data/portfolios/state/ai_analysis_cache.json              # Clear cache
bash linux_launchers/run_portfolio_monthly.sh                # Force fresh AI
```

### Agent System
```bash
.venv/bin/python scripts/agent_router.py --full-refresh
.venv/bin/python scripts/agent_router.py --daily-intel
.venv/bin/python scripts/agent_watchlist_engine.py --daily
.venv/bin/python scripts/overnight_batch.py --outcomes        # Score decisions
.venv/bin/python scripts/overnight_batch.py --proactive       # Auto-queue symbols
.venv/bin/python scripts/overnight_batch.py --index-embeddings
```

### Database
```bash
psql -U trade_ai -d trade_ai                                  # Connect
psql -U trade_ai -d trade_ai -c "SELECT count(*) FROM news_articles;"
psql -U trade_ai -d trade_ai -c "\dt | wc -l"                # Table count
psql -U trade_ai -d trade_ai -c "SELECT event_type, symbol, status, created_at FROM agent_event_queue ORDER BY created_at DESC LIMIT 10;"
psql -U trade_ai -d trade_ai -c "SELECT agent_name, count(*), round(avg(confidence_score)::numeric,2) FROM watchlist_agent_results GROUP BY agent_name;"
```

### Services
```bash
systemctl status tradeai-continuous
systemctl status portfolio-server
sudo systemctl restart tradeai-continuous
sudo systemctl restart portfolio-server
journalctl -u tradeai-continuous -f --since "1 hour ago"
```

---

## Level 3 Event System — ✅ COMPLETE (10/10 events + sector correlation)

| Event | Agents | Priority | Threshold | Cooldown | Status |
|-------|--------|----------|-----------|----------|--------|
| SEC_INSIDER_BUY | Maria, Risk | urgent | Form 4 purchase in 24h | 4h | ✅ |
| RSI_EXTREME | Risk | normal | RSI <25 or >75 in holdings | 4h | ✅ |
| FRED_RATE_CHANGE | Maria, Steph, Risk | urgent | DFF change >0.25% | 4h | ✅ |
| DIVIDEND_CUT | Steph, Tax | urgent | yield drop >20% vs baseline | 4h | ✅ |
| EARNINGS_BEAT | Maria, Steph | normal | EPS beat >10% in 24h | 4h | ✅ |
| STOP_TRIGGERED | Risk, Steph | urgent | price ≤ stop_price in holdings | 4h | ✅ |
| IRMAA_THRESHOLD | Alex, Tax | urgent | MAGI projection > $103K | 24h | ✅ |
| INCOME_FLOOR_RISK | Steph, Alex | urgent | position > $11K/yr income | 24h | ✅ |
| MARKET_REGIME_CHANGE | Risk, Maria | urgent | VIX crosses 25 or 30 | 6h | ✅ |
| PORTFOLIO_FRESH_NEEDED | Risk, Steph | normal | not analyzed >48h (max 3) | 4h | ✅ |
| **SECTOR_CORRELATION_ALERT** | **Maria, Risk** | **urgent** | **3+ events same sector/batch** | **N/A** | **✅ NEW v3.7** |

**Cron lines (both required):**
```
*/15 * * * * cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/event_detector.py >> logs/event_detector.log 2>&1
*/15 * * * * sleep 120 && cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/agent_event_router.py >> logs/event_router.log 2>&1
```

---

## LLM Provider Chain (v3.7)

```
LOCAL qwen3:1.7b  →  GROK grok-3-mini  →  CLAUDE Sonnet  →  OPENAI gpt-4o
```

| Provider | Role now | After GPU | Budget |
|----------|----------|-----------|--------|
| Local qwen3:1.7b | Primary (free) | Replaced by 14b | $0 |
| Grok grok-3-mini | Primary cloud testing | Demoted to fallback | $5/day total |
| Claude Sonnet | Best quality (retirement/disability) | Unchanged | Shared |
| OpenAI gpt-4o | Last resort | Last resort | Shared |

**Task routing (pre-GPU):**
```
agent_narrative    → local → grok → claude
agent_debate       → local → grok → claude   (2-round when divergence >30%)
sector_correlation → grok  → local → claude  (Grok better for macro context)
cio_synthesis      → local → claude → grok → openai
```

**Test commands:**
```bash
.venv/bin/python scripts/llm_router.py --routing     # Show current routing
.venv/bin/python scripts/llm_router.py --test-grok   # Test Grok specifically
.venv/bin/python scripts/llm_router.py --test        # Test all providers
```

---

## .env — Single Source of Truth

**Location:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env`

Required keys:
```
FINVIZ_COOKIE=.ASPXAUTH=...;.AspNetCore.Session=...
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
FRED_API_KEY=...
FINNHUB_API_KEY=...
YOUTUBE_API_KEY=...
ALPHA_VANTAGE_API_KEY=...
FMP_API_KEY=...
BRAVE_SEARCH_API_KEY=...   # 402 until $5 credit added
XAI_API_KEY=...            # Grok — required for v3.7 agent testing
```

GPU switch (add only when qwen3:14b installed):
```
LOCAL_MODEL=qwen3:14b
```

---

## Cron Schedule (65 entries)

```bash
crontab -l    # View all
crontab -e    # Edit (use nano)
```

Key entries:
```
5:00 AM daily       Alex daily scan
5:30 AM daily       Outcome evaluation (score past decisions, extract 7 lessons)
6:00 AM daily       Smart alerts + credential check
6:25 AM daily       Agent intel daily (Maria/Steph/Risk batch)
6:30 AM daily       FRED macro ingest + news ingestion
7:00 AM daily       CIO decisions + dividend sync
8:00 AM daily       Aegis morning brief → Telegram + event digest
*/15 * * * *        event_detector.py (Level 3 — every 15 min ALL DAY)
*/15+2min  * * * *  agent_event_router.py (Level 3 — 2 min after detector)
7:00 PM daily       YouTube ingest + watchlist engine
9:00 PM daily       Embedding indexing
Sunday 8 AM         Autonomy summary → Telegram
Sunday 10 AM        Weekly retirement health check
1st of month 9 AM   Monthly retirement performance report
```

---

## Key Files (v3.7 — changed files marked)

| File | Purpose | v3.7 |
|------|---------|------|
| `scripts/intel_query.py` | Agent context builder — every prompt goes through here | ✅ CHANGED |
| `scripts/agent_watchlist_engine.py` | Intel promotion, debate, rotation proposals | ✅ CHANGED |
| `scripts/agent_event_router.py` | Level 3 queue drainer | ✅ CHANGED |
| `scripts/llm_router.py` | LLM routing + GPU failback | ✅ CHANGED |
| `scripts/event_detector.py` | Level 3 — 10 event types, every 15 min | No change |
| `scripts/system_preflight_check.py` | 23-test health check | No change |
| `scripts/alex_retirement_advisor.py` | Retirement + disability analysis | No change |
| `scripts/portfolio_server.py` | Dashboard server (port 7777) | No change |
| `scripts/overnight_batch.py` | Outcome eval, proactive scan, embeddings | No change |
| `data/portfolios/state/risk_management.json` | Source for heat injection (#4) | Read by intel_query |
| `data/portfolios/state/holdings.json` | Live holdings — 4 accounts | Read by intel_query |

---

## Common Diagnostics

| Problem | SSH Command to Diagnose |
|---------|------------------------|
| preflight FAIL services | `sudo systemctl restart tradeai-continuous` |
| portfolio-server down | `ps aux | grep portfolio_server` then start via nohup |
| No Trade AI tickers | `.venv/bin/python scripts/system_preflight_check.py` — Finviz cookie |
| Agents returning empty | `LOCAL_TIMEOUT=30` in llm_router.py + Ollama running |
| Grok not responding | `XAI_API_KEY` in .env + `.venv/bin/python scripts/llm_router.py --test-grok` |
| Heat context missing | `cat data/portfolios/state/risk_management.json | grep heat` |
| Debate only 1 round | Normal — Round 2 only when divergence >30%. Check logs for `[debate]` lines |
| No sector correlation | Need 3+ symbols with same strategy in same 15-min batch |
| Event queue backed up | `.venv/bin/python scripts/agent_event_router.py --status` |
| Ollama empty response | Timeout issue — `LOCAL_TIMEOUT` must be 30 in llm_router.py |
| Finviz 0 tickers | URL must be `/export` not `/export.ashx` |

---

## What to Build / Do Next

| Priority | Action | Status |
|----------|--------|--------|
| **NOW** | Fix 2 preflight failures (tradeai-continuous + portfolio-server) | See "Fix Service Failures" above |
| **TODAY** | Review 5 stop proposals on `/v2/approvals` (TDG, RTX, LMT, LHX, NOC) | Feeds learning loop |
| 1 | Top up Brave Search — $5 unlocks real-time web research | Pending |
| 2 | GPU upgrade — qwen3:14b. One line: `echo "LOCAL_MODEL=qwen3:14b" >> .env` | Pending |
| 3 | Run 30 days — outcome lessons accumulate (started May 1, 2026) | In progress |
| ✅ | ~~Agent improvements #2,3,4,5,6~~ | Done v3.7 May 1 |
| ✅ | ~~Event digest in Aegis brief~~ | Done v3.6 |
| ✅ | ~~All 10 event types~~ | Done v3.2 |
| ✅ | ~~Level 3 event_detector + router~~ | Done v3.1 |

---

## Changelog

- **v3.7** (May 1, 2026) — Agent improvements deployed: heat injection (#4), market session (#6), cross-agent reasoning (#2), sector correlation detection (#5), 2-round debate (#3). Grok `grok-3-mini` as primary testing provider. GPU auto-failback via `LOCAL_MODEL` env var. Budget $2→$5/day. 158 tables, 1652 agent analyses, 830 news articles.
- **v3.6** — Event digest in Aegis brief (Telegram + API). First overnight: 42 events. 151 tables.
- **v3.5** — Trade Journal PostgreSQL migration (627 transactions, 122 closed). FIFO fix.
- **v3.3–3.4** — Level 3 complete. 8 events processed. Telegram delivered. Retry logic.
- **v3.1–3.2** — event_detector.py + agent_event_router.py. All 10 event types. Cron 63→65.
- **v3.0** — Autonomous agent ruleset, Mermaid diagrams, Level 3 roadmap.

---

*SKILL.md v3.7 — SSH: johnclaw@192.168.50.16 — Project: /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/*
*System Bible: TRADE_AI_V12_SYSTEM_BIBLE_V3.md — full architectural detail*
*Deploy zip: agent_improvements_v37.zip — see "Deploy v3.7" section*
