---
name: trade-ai-v12
description: >
  Full-stack autonomous trading intelligence + retirement planning system running on
  ms01-openclaw (Ubuntu Linux). Use this skill when the user wants to: run any pipeline,
  check agent results, interpret GO/WAIT/NO GO tickers, debug cron jobs, work with
  PostgreSQL data, modify agent behavior, check portfolio health, run retirement analysis,
  review proposals, manage screeners, fix broken APIs, check credential status, understand
  agent decisions, build Level 3 autonomous features, work with the intelligence whiteboard,
  or anything related to the Trade AI v12 or Portfolio Intelligence v1.2 system.
  Also trigger on: "run trade ai", "check my agents", "what's moving", "check my portfolio",
  "why did the agent", "run the pipeline", "fix the cron", "check the DB", "what did Maria find",
  "show proposals", "run monthly", "event detector", "level 3", "autonomous", or any variation.
---

# Trade AI v12 + Portfolio Intelligence v1.2 — System Skill

**Server:** ms01-openclaw (Ubuntu Linux, NOT Windows)
**SSH:** `ssh johnclaw@192.168.50.16`
**Project root:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/`
**Dashboard (main):** `http://192.168.50.16:7777/v2` (served by `portfolio_server.py`)
**Agent Monitor:** `http://192.168.50.16:7777/agent-monitor` (LLM spend, agent health, event queue)
**Orchestration:** `http://192.168.50.16:7777/reports/agent_orchestration.html` (pipeline view)
**LLM Spend API:** `http://192.168.50.16:7777/api/v2/llm-spend`
**Pipeline API:** `http://192.168.50.16:7777/api/v2/agent-pipeline` (jobs/results/handoffs/events/proposals/debates)
**Proposal Detail:** `http://192.168.50.16:7777/api/v2/proposal-detail/<id>` (position, agents, news, stops, outcomes, pnl_summary)
**Task Detail:** `http://192.168.50.16:7777/api/v2/task-detail/<id>` (stop-triggered items: entry/current/stop/P&L/breached/agents/news)
**Symbol Context:** `http://192.168.50.16:7777/api/v2/watchlist/context/<symbol>` (agent narratives, synthesis, strategy, news, intel, holdings, outcomes, conflict detection)
**System Health API:** `http://192.168.50.16:7777/api/v2/system-health`
**Database:** PostgreSQL — `trade_ai` — localhost:5432
**Live stats:** `http://192.168.50.16:7777/api/v2/system-health`
**System Bible:** `TRADE_AI_V12_SYSTEM_BIBLE_V3.md` (canonical reference — check this first for any system question)

---

## CRITICAL: This system runs on Linux, not Windows

All paths use forward slashes. Commands use `python3`, not `python`. Launchers are `.sh`, not `.bat`.

```bash
# CORRECT
python3 scripts/trade_ai_orchestrator.py --run-label 0900
source .env

# WRONG (old Windows docs — ignore)
python scripts\trade_ai_orchestrator.py
run_portfolio.bat
```

---

## Quick Commands

### Preflight (run before AND after any session)
```bash
python3 scripts/system_preflight_check.py
# 23 tests. Expected: 18-19 pass. One SKIP is normal (nohup vs systemd).
```

### Trade AI
```bash
# Test run (no alerts, no LLM cost — safe any time)
python3 scripts/trade_ai_orchestrator.py --run-label 0900 --skip-market-check --no-alerts --no-llm

# Standard run (valid labels: 0400 0700 0900 1000)
python3 scripts/trade_ai_orchestrator.py --run-label 0700

# Health check
python3 scripts/trade_ai_health.py --project-root .
```

### Portfolio Intelligence
```bash
# Daily pipeline
bash linux_launchers/run_portfolio.sh

# Force fresh AI analysis
rm data/portfolios/state/ai_analysis_cache.json
bash linux_launchers/run_portfolio_monthly.sh

# Price cache
bash linux_launchers/run_price_cache.sh
```

### Agent System
```bash
# Run full agent daily cycle
python3 scripts/agent_router.py --full-refresh
python3 scripts/agent_router.py --daily-intel

# Run watchlist engine (promote intel + propose rotations + discovery)
python3 scripts/agent_watchlist_engine.py --daily

# Overnight batch
python3 scripts/overnight_batch.py --outcomes        # Score past decisions
python3 scripts/overnight_batch.py --proactive       # Auto-queue high-Q symbols
python3 scripts/overnight_batch.py --index-embeddings # Index new embeddings
python3 scripts/overnight_batch.py --research        # Re-analyze research topics

# Autonomy summary
python3 scripts/agent_watchlist_engine.py --autonomy-summary --telegram
```

### Credentials
```bash
python3 scripts/credential_monitor.py --check
# Or Telegram: "check credentials"
# Or Telegram: "update FINVIZ_COOKIE .ASPXAUTH=..."
```

### FRED Macro
```bash
python3 scripts/fred_data_ingest.py --ingest
python3 scripts/fred_data_ingest.py --status
python3 scripts/fred_data_ingest.py --context    # Human-readable FRED context string
```

### Alex Retirement Advisor
```bash
python3 scripts/alex_retirement_advisor.py --analyze V --tax-advisor
python3 scripts/alex_retirement_advisor.py --roth-ladder
python3 scripts/alex_retirement_advisor.py --weekly-health --telegram
python3 scripts/alex_retirement_advisor.py --monthly-report --telegram
```

### Config Sync (YAML → DB)
```bash
python3 scripts/config_sync.py --status    # Show current sync state
python3 scripts/config_sync.py --sync      # Push YAML config to DB
python3 scripts/config_sync.py --dry-run   # Preview changes without writing
```

---

## .env Location — SINGLE SOURCE OF TRUTH

```
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env   ← ONLY file. Never create others.
```

Every script uses `set -a; source .env; set +a` in launchers.
`load_dotenv()` in Python scripts finds root `.env` by CWD search.

Required keys: `FINVIZ_COOKIE`, `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `FRED_API_KEY`, `FINNHUB_API_KEY`, `YOUTUBE_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `FMP_API_KEY`, `BRAVE_SEARCH_API_KEY`

---

## Database Quick Reference

```bash
# Connect
psql -U trade_ai -d trade_ai

# Live system stats (always current)
psql -U trade_ai -d trade_ai -c "
SELECT 
  (SELECT count(*) FROM news_articles) as news_articles,
  (SELECT count(*) FROM watchlist_agent_results) as agent_analyses,
  (SELECT count(*) FROM content_embeddings) as embeddings,
  (SELECT count(*) FROM watchlist_proposals WHERE status='proposed') as pending_proposals,
  (SELECT count(*) FROM agent_event_queue WHERE status='pending') as pending_events,
  (SELECT count(*) FROM trade_transactions) as transactions,
  (SELECT count(*) FROM trade_closed) as closed_trades;
"

# OR via API (no SSH needed):
# http://192.168.50.16:7777/api/v2/system-health  ← DB tables + agent counts
# http://192.168.50.16:7777/api/v2/llm-spend      ← today's LLM spend + calls

# Agent confidence (live):
SELECT agent, count(*) as analyses, 
       round(avg(confidence)::numeric,2) as avg_conf
FROM watchlist_agent_results GROUP BY agent ORDER BY avg_conf DESC;

# Pending proposals:
SELECT symbol, action, strategy_type, confidence, status
FROM watchlist_proposals WHERE status='proposed' ORDER BY created_at DESC LIMIT 10;

# Outcome lessons:
SELECT rule_key, config->>'lesson' as lesson
FROM agent_intelligence_rules WHERE rule_type='outcome_lessons';

# Enable auto-execute (DISABLED by default):
UPDATE agent_intelligence_rules
SET config = jsonb_set(config, '{enabled}', 'true')
WHERE rule_type = 'auto_execute' AND rule_key = 'low_risk';
```

---

## Systemd Services

```bash
# Check status
systemctl status tradeai-continuous
systemctl status portfolio-server    # May run via nohup instead

# Restart
sudo systemctl restart tradeai-continuous
sudo systemctl restart portfolio-server

# Logs
journalctl -u tradeai-continuous -f
journalctl -u portfolio-server -f --since "1 hour ago"
```

---

## Cron

```bash
crontab -l                    # View all crons
crontab -l | wc -l            # Count entries

# Key cron timing reference
# 5:00 AM  - Alex daily scan
# 5:30 AM  - Outcome evaluation
# 6:00 AM  - Smart alerts + credential check
# 6:15 AM  - Agent router refresh
# 6:25 AM  - Agent intel daily
# 6:30 AM  - FRED ingest + news ingestion
# 7:00 AM  - CIO decisions
# 8:00 AM  - Aegis morning brief → Telegram
# 7:00 PM  - YouTube ingest + agent watchlist engine
# 9:00 PM  - Embedding indexing
# 10PM-6AM - Transcript backlog (2/hour)
# */15 min  - Event detector + router (Level 3)
# Sunday 8AM  - Autonomy summary
# Sunday 10AM - Weekly retirement health check
# 1st 9AM     - Monthly retirement report
```

---

## Agent System Reference

### Seven agents

| Agent | Model | Role |
|-------|-------|------|
| Maria | qwen3:1.7b (two-pass) | Research: news→fundamentals |
| Steph | qwen3:1.7b | Allocation & income |
| Risk | qwen3:1.7b | Technical analysis |
| Tax | qwen3:1.7b | Tax optimization (on-demand) |
| Alex | Claude Sonnet | Retirement + disability (48 rules, 3-tier hygiene, gov scrapers) |
| Aegis | Claude/local | Morning brief (daily 8 AM) |
| Iris | Claude Sonnet/local | Taxonomy + content hygiene (2 modes, Telegram presence) |

Live confidence: `SELECT agent, round(avg(confidence)::numeric,2) FROM watchlist_agent_results GROUP BY agent;`

### What every agent receives (injected automatically)
1. Portfolio context (holdings, income gap, tax bracket)
2. FRED macro context (7 series — auto from `get_macro_context()`)
3. Qualified intel (news + YouTube key points + SEC Form 4 + AV fundamentals)
4. Outcome lessons (last 7 correct/wrong decisions from `agent_intelligence_rules`)
5. SSDI rules (Medicaid lookback, IRMAA thresholds, MFS bracket ceiling)
6. Cross-agent views (prior results from other agents on same symbol)

### Non-negotiable agent rules
- **G2 — Income Protection:** NEVER auto-rotate income-critical positions (>$11K/yr income contribution)
- **G3 — SSDI Awareness:** Every IRA/401k recommendation must compute MAGI impact + IRMAA/Medicaid flags
- **G4 — Confidence Gate:** No recommendation if confidence <40%
- **G9 — Debate Required:** 3-agent debate (Maria+Steph+Risk) must reach ≥50% consensus before Alex queue
- **G10 — No Execution:** Auto-execute is DISABLED. All trade instructions require human approval.

### Escalation path
Conflict or income-critical → `agent_handoffs` table → Alex → CIO decision → `trade_instructions`

### Alex Three-Tier Decision Hygiene (v4.6)
File: `scripts/alex_hygiene.py`

| Tier | Cost | Providers | Use cases |
|------|------|-----------|-----------|
| Tier 1 (routine) | ~$0.01 | Sonnet alone | Daily monitors, stop reviews, weekly health |
| Tier 2 (significant) | ~$0.03 | Sonnet + Grok | Roth conversions, IRMAA review, rebalance |
| Tier 3 (critical) | ~$0.15 | Sonnet + Grok + GPT-4o → Opus synthesis | Trusts, large conversions, estate planning |

Cadence gate: Tier 3 enforced to 30-day minimum. Bypass for new laws, IRMAA crossing, inheritance.
Agreement scoring: 1.0 = unanimous, 0.67 = 2-vs-1, 0.33 = split.
DB: `alex_hygiene_log`. API: POST `/api/v2/alex-hygiene/classify`, `/api/v2/alex-hygiene/run`.

### Alex Disability Intelligence (v4.6)
File: `scripts/alex_retirement_advisor.py` — 48 rules in 5 categories (SSDI, Dual Eligibility, Trust, Roth+Disability, IRMAA).
File: `scripts/alex_gov_research.py` — 4 government scrapers (SSA, IRMAA, Medicaid NY, Roth IRA). 30-day cache. Cron: Sunday 8 AM.

### Iris Content Hygiene (v4.9)
File: `scripts/iris_taxonomy_agent.py` — `--hygiene` mode

| Content type | Active window | Then |
|-------------|--------------|------|
| General news | 90 days | Auto-archive |
| Tax/retirement news | 365 days | Auto-archive |
| Disability news | 18 months | Escalate to John |
| YouTube: general | 1 year | Auto-archive |
| YouTube: disability | 3 years | Escalate to John |
| YouTube: evergreen | Never | Never expires |

Cron: Sunday 6 AM. Telegram: `iris hygiene status/approve/reject/defer/preview/run`.
API: GET `/api/v2/iris/hygiene-status`. DB: `iris_hygiene_log`, `iris_hygiene_pending`.

### Per-Transcript Deep Tagging (v4.8)

File: `scripts/transcript_tagger.py`

Every YouTube transcript gets individually classified based on its own content — NOT just channel inheritance.

**TWO LAYERS:**
- Layer 1 — Channel baseline: channel category assigns default agents
- Layer 2 — Content analysis: title + full transcript text overrides Layer 1 if confidence >= 60%

**QUALITY SCORING (per transcript, not per channel):**
Base: 50pts | Long (5K+ words): +12 | Medium (2K+): +8 | Short (<500): -10
Current year in title: +8 | High-value keywords (irmaa, ssdi, special needs trust): +8 to +12 each
Multi-agent content: +4 to +6 | Channel category bonus: +6 to +10
Range: 0-100 (disability/retirement content typically 70-95)

**PROMOTION THRESHOLDS:** alex-tagged: Q>=55 | retirement: Q>=60 | standard: Q>=70

**INGEST HOOK:** Called automatically on every new transcript INSERT. Never leaves a transcript untagged.

**CLI:**
```
python3 scripts/transcript_tagger.py               # show stats
python3 scripts/transcript_tagger.py --test         # test 10 transcripts
python3 scripts/transcript_tagger.py --all          # tag untagged
python3 scripts/transcript_tagger.py --retag-all    # force re-tag all
python3 scripts/transcript_tagger.py --id 123       # tag single
```

**API:** `GET /api/v2/transcript-audit`

---

## Intelligence Pipeline (5 Levels)

| Level | Name | LLM | Condition |
|-------|------|-----|-----------|
| L0 | Raw | None | Auto-promoted on ingest |
| L1 | Scored | None | Keyword scoring, all content |
| L2 | Iterating | qwen3:1.7b | Q≥50 + 1+ day old |
| L3 | Validated | qwen3:1.7b | 2+ sources OR (3+ days + Q≥75) |
| L4 | Promoted | qwen3:1.7b | Q≥70 + agent_tags + dashboard visible |
| L5 | Synthesized | Claude | Debate ≥50% + Alex analysis |

Managed by `agent_watchlist_engine.py` — runs daily 7 PM.

---

## Screeners (22 active)

| Schedule | Count | Strategies |
|----------|-------|-----------|
| Daily | 4 | day_scalp, swing_trade, speculative_growth |
| Weekly | 9 | dividend_growth, covered_call, high_yield, income |
| Biweekly | 4 | core_growth, defense_thesis, core_holding, index |
| Monthly | 5 | recovery, international, reit, bond |

All use `elite.finviz.com/export` (NOT `export.ashx` — Finviz changed this April 29, 2026).
Fallback chain: v=152 → v=151 → v=141 → v=111.

---

## Trade AI Scoring (max 55 pts)

| Pillar | Max | Key trigger |
|--------|-----|-------------|
| Catalyst | 15 | FDA, earnings beat, M&A, 8-K |
| RVOL | 12 | ≥8× max; ≥5× near max |
| Price Action | 10 | Gap% + change% + RVOL alignment |
| Float | 8 | <5M = max; >100M = 0 |
| Price Range | 5 | $2–$10 sweet spot |
| Sector Momentum | 5 | Sector ETF top 3 |

GO ≥40 · WAIT 30-39 · NO GO <30 · A+ ≥48 (Sonnet trade plan)
**All Trade AI setups execute in Taxable account only.**

---

## LLM Router — Critical Settings

```python
# scripts/llm_router.py
LOCAL_TIMEOUT = 30           # Was 8 — qwen3 needs 15-20s for thinking mode
LOCAL_NUM_PREDICT = max(500, max_tokens)   # Was max_tokens (could be 50 — too low)
LOCAL_MODEL = "qwen3:1.7b"   # Was qwen3:14b (not installed)
```

Cloud fallback chain: Claude → Grok → OpenAI
Budget gate: $0.50/day. At limit → falls back to local qwen3.
Live spend: `http://192.168.50.16:7777/api/v2/llm-spend`

---

## Key Files

| File | Purpose |
|------|---------|
| `.env` | All API keys — project root only |
| `scripts/system_preflight_check.py` | 23-test health check — run first |
| `scripts/trade_ai_orchestrator.py` | Main 23-stage Trade AI pipeline |
| `scripts/agent_router.py` | Dispatches agent analyses |
| `scripts/agent_watchlist_engine.py` | Promotes intel, proposes rotations, debate |
| `scripts/overnight_batch.py` | Outcome eval, proactive scan, embeddings |
| `scripts/event_detector.py` | Level 3: event-driven agent triggers (10 types, */15 cron) |
| `scripts/agent_event_router.py` | Level 3: drains event queue → agent jobs → Telegram |
| `scripts/process_watchlist_agent_jobs.py` | Runs agent LLM calls (Maria two-pass in here) |
| `scripts/alex_retirement_advisor.py` | Alex retirement + disability analysis |
| `scripts/fred_data_ingest.py` | FRED macro data pipeline |
| `scripts/credential_monitor.py` | Daily credential health check |
| `scripts/config_sync.py` | Sync YAML config → PostgreSQL |
| `scripts/llm_router.py` | LLM routing + fallback (LOCAL_TIMEOUT=30) |
| `scripts/intel_query.py` | Agent intel context builder (injects FRED + lessons) |
| `scripts/portfolio_trade_journal.py` | FIFO trade matcher — builds closed_trades from raw transactions |
| `scripts/portfolio_server.py` | HTTP server — serves dashboard + APIs |

---

## Level 3 Autonomous Agent Feature — ✅ COMPLETE

Agents self-trigger on 10 data events every 15 minutes. Event digest in Aegis brief.

### Event types (all live)

| Event | Agents | Priority | Cooldown |
|-------|--------|----------|----------|
| SEC_INSIDER_BUY | Maria, Risk | urgent | 4h |
| RSI_EXTREME | Risk | normal | 4h |
| FRED_RATE_CHANGE | Maria, Steph, Risk | urgent | 4h |
| DIVIDEND_CUT | Steph, Tax | urgent | 4h |
| EARNINGS_BEAT | Maria, Steph | normal | 4h |
| STOP_TRIGGERED | Risk, Steph | urgent | 4h |
| IRMAA_THRESHOLD | Alex, Tax | urgent | 24h |
| INCOME_FLOOR_RISK | Steph, Alex | urgent | 24h |
| MARKET_REGIME_CHANGE | Risk, Maria | urgent | 6h |
| PORTFOLIO_FRESH_NEEDED | Risk, Steph | normal | 4h |

### Cron (both scripts)
```
*/15 * * * * cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/event_detector.py >> logs/event_detector.log 2>&1
*/15 * * * * sleep 120 && cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/agent_event_router.py >> logs/event_router.log 2>&1
```

---

## Telegram Commands (32 unique)

| Command | What |
|---------|------|
| `status` | Full system dashboard |
| `tax` | Bracket, room, Roth YTD |
| `intel SCHD` | Recent intelligence for SCHD |
| `alex V` | Full retirement analysis for V |
| `roth ladder` | 5-year Roth conversion projection |
| `conflicts` | Agent disagreement count |
| `iris status` | Coverage %, pending proposals, top gap |
| `iris <question>` | Ask Iris anything about content tagging |
| `iris approve <id>` | Approve a keyword proposal — activates immediately |
| `iris reject <id>` | Reject a keyword proposal |
| `iris run` | Force taxonomy scan (~90s) |
| `iris who` | Iris identity and command help |
| `iris hygiene` | Pending hygiene decisions |
| `iris hygiene approve N` | Approve a content demotion |
| `iris hygiene reject N` | Keep content active |
| `iris hygiene defer N` | Decide in 7 days |
| `iris hygiene preview` | Dry run — see what would change |
| `iris hygiene run` | Force hygiene run now |
| `research TOPIC` | Persistent research topic |
| `monthly report` | Monthly retirement performance |
| `check credentials` | All 10 credentials status |
| `run screener NAME` | Run a specific screener |
| `analyze SYMBOL` | Full LLM analysis |
| `find WHAT` | Discovery + persist |
| `topics` | List active research |
| `help` | List all available commands |
| `update KEY VALUE` | Update .env credential (allowed keys only) |
| `/iris_approve_N` | Shortcut: approve Iris proposal #N |
| `/iris_reject_N` | Shortcut: reject Iris proposal #N |
| `iris library` | RAG coverage + stale + dupes + gaps summary |
| `iris stale` | Symbols not analyzed by agents in >7 days |
| `iris gaps` | Content categories with thin recent coverage |

---

## Scripts & Cron Cheat Sheet

### Pipeline scripts (run by cron — 71 entries)

| Script | Schedule | What it does | Key args |
|--------|----------|--------------|----------|
| `run_alex_daily.py` | 5:00 AM M-F | Alex daily retirement scan → Telegram | `--daily --telegram` |
| `overnight_batch.py` | 5:30 AM / 6:45 AM / 8 PM / 9 PM | Outcomes, proactive scan, nightly pipeline, embeddings | `--outcomes` / `--proactive` / `--telegram` / `--index-embeddings` |
| `telegram_smart_alerts.py` | 6:00 AM M-F | Roth/income/conflict/stop/Medicare alerts | `--check-all --telegram` |
| `credential_monitor.py` | 6:00 AM daily | Check 10 API credentials | `--check --telegram` |
| `fred_data_ingest.py` | 6:30 AM M-F | FRED macro (7 series) | `--ingest` |
| `news_ingestion.py` | 6:30 AM / 12:30 PM / 6:30 PM | Yahoo RSS + Finnhub + Google News | `--priority` |
| `classify_candidates.py` | 6:35 AM M-F | Classify new symbols into strategies | — |
| `intel_auto_discovery.py` | 6:40 AM + 12:40 PM M-F | Scan for new ticker mentions | `--telegram` |
| `finviz_enrichment.py` | 7:10 AM + 1:00 PM M-F | RSI, SMA, ATR, beta enrichment | — |
| `cio_decision_engine.py` | 7:00 AM M-F | CIO synthesis → decisions | `--run` |
| `aegis_morning_brief_delivery.py` | 8:05 AM M-F | Morning brief → Telegram + export | — |
| `finviz_screener_runner.py` | 10:00 AM + 4:00 PM M-F | Run 22 Finviz screeners | `--run` |
| `youtube_transcript_ingest.py` | 7:00 PM M-F | Ingest from 44 channels | `--all-channels` |
| `agent_watchlist_engine.py` | 7:00 PM M-F / Sun 10 AM | Daily + weekly watchlist engine | `--daily` / `--weekly --telegram` |
| `sec_data_ingest.py` | 8:00 PM M-F | SEC EDGAR Form 4 insider filings | `--all` |
| `event_detector.py` | Every 15 min 24/7 | Level 3: 10 event types → queue | — |
| `agent_event_router.py` | Every 15 min 24/7 (+2m) | Drain event queue → agent jobs → Telegram | — |
| `process_watchlist_agent_jobs.py` | Every 5–15 min 24/7 | Process queued agent analysis jobs | `--limit 10/15/25` |
| `iris_taxonomy_agent.py` | Sunday 6 AM | Content hygiene — demote stale, flag superseded | `--hygiene` |
| `alex_gov_research.py` | Sunday 8 AM | Government data refresh (SSA, IRMAA, Medicaid) | `--refresh` |
| `full_system_backup.py` | Sunday 1 AM | Full system backup zip | — |
| `youtube_channel_discovery.py` | 1st of month 10 AM | Discover new channels | `--discover --telegram` |

| `rag_indexer.py` | 6:50 AM / 7:20 PM / 2:30 AM | RAG embedder: news+FRED / YouTube / agent outputs | `--source all --hours 2` / `--backfill` |

### On-demand scripts (manual or API-triggered)

| Script | Trigger | What it does | Key args |
|--------|---------|--------------|----------|
| `phase2_ticker_enrichment.py` | API / auto-enrich | Fresh price + news + SEC for a symbol | `--symbol SYM` |
| `alex_retirement_advisor.py` | Telegram `alex V` | Full retirement analysis | `--analyze SYM` |
| `alex_hygiene.py` | API | 3-tier decision hygiene (Sonnet/Grok/GPT-4o/Opus) | `--classify` / `--run` |
| `iris_taxonomy_agent.py` | Telegram `iris run` | Taxonomy scan: coverage gaps, proposals | — (default) |
| `transcript_tagger.py` | Post-ingest hook | Per-transcript quality + strategy + agent tagging | `--retag-all` / `--id N` |
| `telegram_command_handler.py` | Telegram polling | Parse 29 Telegram commands | `--poll` |
| `system_preflight_check.py` | Manual | Verify data sources, credentials, DB | — |
| `portfolio_orchestrator.py` | Manual | Full pipeline (reprice, stops, risk, reports) | — |

### Server processes

| Script | Port | What it does |
|--------|------|--------------|
| `portfolio_server.py` | 7777 | Main HTTP server — /api/v2/*, React app, static files |

### Utility / library scripts

| Script | What it does |
|--------|--------------|
| `api_v2.py` | All /api/v2/* route handlers (imported by portfolio_server.py) |
| `db_adapter.py` | PostgreSQL connection, query wrappers, action_queue upsert |
| `local_llm.py` | Ollama qwen3:1.7b with OpenAI/Claude fallback chain |
| `llm_router.py` | LLM routing with budget tracking ($0.50/day) |
| `content_scoring.py` | Keyword quality/relevance scoring for news + YouTube |
| `telegram_alert.py` | Send message via Telegram Bot API |
| `intel_query.py` | Query whiteboard, agent_results, market session context |
| `scoring.py` | Trade AI 6-pillar scoring engine (55 pts max) |

---

## Trust Matrix (what to rely on)

**HIGH TRUST:** Portfolio tracking, tax bracket math, income gap, DB infrastructure, FRED macro, SEC Form 4, preflight check
**MEDIUM TRUST:** Maria (check live: `SELECT round(avg(confidence)::numeric,2) FROM watchlist_agent_results WHERE agent='maria'`), news tagging, content scoring (keyword-based)
**LOW TRUST / IGNORE:** CIO decisions (suggestions only), decision outcomes (accumulating), MARL (shadow only)

---

## Operator Decision Rules

**Act on recommendation only when ALL true:**
- `synthesis.confidence` > 60%
- No agent conflict (BUY vs SELL)
- Not income-critical (>20% of $55K target)
- Decision < 7 days old

**Always human review:**
- Income asset TRIM/SELL
- Confidence 40–60%
- Any Roth conversion
- IRMAA/SSDI flag set
- Position > 5% of portfolio

**Ignore:**
- Confidence < 40%
- Single agent only (no synthesis)
- Decision > 14 days old

---

## 401k Constraint

```yaml
# assets/portfolio_accounts.yaml
fidelity_401k_constraints:
  constraint_active: true    # Set false after 2027 rollover
  rollover_target_date: "2027-12-31"
```

AI analyst constrained to 15 Omnicom plan funds until rollover.
Preferred: SP500-D (0.015% ER), SS-GACEQ, FID-CONTRA-F
Avoid: WM-BLAIR (weak perf), OMC (company stock), STABLE-VALUE

---

## Common Diagnostics

| Problem | Command |
|---------|---------|
| No Trade AI tickers | `python3 scripts/system_preflight_check.py` — check Finviz cookie + URL |
| Agents returning empty | Check `llm_router.py`: LOCAL_TIMEOUT must be 30, not 8 |
| Morning brief missing | Check `aegis_morning_brief_delivery.py` — verify export path exists |
| Stop prices $0.00 | Check `portfolio_orchestrator.py` — must pass real prices, not hardcoded 0 |
| Header shows 0 GO | Check `api_v2.py` — reads both `goCount` and `go_count` with fallback |
| DB tables missing | check: `psql -U trade_ai -d trade_ai -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"` |
| Cron not firing | `crontab -l` — verify paths are absolute, `.env` sourced in launcher |
| Ollama empty response | Timeout too low — `LOCAL_TIMEOUT=30` in `llm_router.py` |
| Finviz 0 tickers | URL must be `/export` not `/export.ashx` (Finviz changed April 2026) |
| CSV import fails | Schwab CSVs have metadata lines before header — parser finds header row by "Symbol" keyword |
| Journal missing trades | After importing transactions, rebuild: `build_trade_journal()` then update DB `trade_closed` |
| FIFO cost wrong | Check `portfolio_trade_journal.py` line 58 — Security Transfer/Journaled Shares must be in buy list |
| LLM spend too high | Check `/api/v2/llm-spend` — budget is $0.50/day, verify Maria Pass 2 uses `agent_narrative` not `cio_synthesis` |
| Failed agent jobs | `psql -U trade_ai -d trade_ai -c "SELECT submitted_from, requested_agent, count(*) FROM watchlist_agent_jobs WHERE status='failed' AND created_at > NOW() - INTERVAL '24h' GROUP BY 1,2"` |
| 0 debates running | Debate only fires for Q≥75 qualified intel — check `agent_watchlist_engine.py` promote_qualified_intel() |
| Approval modal no context | Check `/api/v2/proposal-detail/<id>` — verify holdings, agent_results, news all returning data |
| Agent conflict seems wrong | RESEARCH_MORE <40% conf is NOT a conflict — it means insufficient data. Real conflicts need opposing directions both >40% conf |
| Watchlist modal missing data | Check `/api/v2/watchlist/context/<symbol>` — verify agent_results and news returning data |
| agent_name undefined in API | watchlist_agent_results uses `agent` and `confidence` — aliased to `agent_name`/`confidence_score` in SELECT |
| Risk RESEARCH_MORE, others BUY | Risk-first gate: if Risk <40% conf, enrichment runs before Maria/Steph. Check `_check_symbol_data_quality()` in process_watchlist_agent_jobs.py |
| Watchlist price shows NO DATA | Symbol missing from enrichment cache — pipeline runs at 7 PM enrich via yfinance. Manual: `python3 scripts/phase2_ticker_enrichment.py --symbol SYM` |
| AV sentiment not in context | Run: `python3 scripts/external_market_data_ingest.py --news-sentiment` (25 symbols/day free tier) |
| Alex not seeing gov thresholds | Run: `python3 scripts/alex_gov_research.py --refresh` (caches 30 days, weekly cron Sunday 8 AM) |
| YouTube channel not classified | Check: `psql -U trade_ai -d trade_ai -c "SELECT channel_name, category FROM youtube_channels WHERE category IS NULL"` |
| Transcripts not promoted | Run /api/v2/youtube-audit — check avg_quality vs auto_promote_threshold per channel |
| New channel needs adding | Use Telegram: `iris run` to scan for gaps, or manually: `INSERT INTO youtube_channels (channel_name, channel_id, category, priority, agent_tags, active, added_by) VALUES ('Name', 'UC...', 'category', 'medium', '{maria,steph}', true, 'john')` |
| Disability YouTube not tagged | Check: `SELECT count(*) FROM youtube_channels WHERE category='disability_retirement'` (should be 7+) |
| FMP analyst ratings | FMP legacy endpoints dead since Aug 2025 — use AV AnalystTargetPrice instead |
| Notes not saved on approval | Check decision_note column: `SELECT decision_note FROM watchlist_proposals WHERE decision_note IS NOT NULL LIMIT 5` |
| Agents not learning from notes | Check john_preferences: `SELECT config FROM agent_intelligence_rules WHERE rule_type='john_preferences' LIMIT 5` |
| P&L not showing in approval | Use `/api/v2/proposals-with-pnl` for batch or `/api/v2/proposal-detail/<id>` for single |
| Task modal shows no P&L | Use `/api/v2/task-detail/<id>` — reads holdings.json cost_basis + risk_management stops |
| Proposal P&L empty for BBVA | Symbol not held — proposal-detail returns empty position (correct for watchlist-only) |
| Tier 3 blocked by cadence | Check `alex_hygiene_log` — last run date. Use `bypass_event` for urgent |
| Grok failing in hygiene | Check `XAI_API_KEY` in .env + x.ai API status |
| GPT-4o failing in hygiene | Check `OPENAI_API_KEY` in .env |
| Iris hygiene escalations piling up | `iris hygiene status` — review pending decisions, approve/reject/defer |
| Content wrongly demoted | `iris hygiene reject <id>` or check: `SELECT * FROM iris_hygiene_log ORDER BY created_at DESC LIMIT 10` |
| Old content still reaching agents | Run: `python3 scripts/iris_taxonomy_agent.py --hygiene-dry-run` |
| All transcripts same quality score | Run: `python3 scripts/transcript_tagger.py --retag-all` |
| Transcripts not reaching Alex | Check strategy detection: `python3 scripts/transcript_tagger.py --id <id>` |
| Channel override seems wrong | Check: `SELECT title, agent_tags, strategy_tags FROM youtube_transcripts WHERE id=<id>` |
| News count 0 in context API | news_articles `symbol` column is correct — check if symbol has any news: `SELECT count(*) FROM news_articles WHERE symbol='SYM'` |
| SmartTextarea mic not working | Chrome only — Web Speech API not in Firefox/Safari |
| AI rewrite returns error | Local LLM (qwen3:1.7b) offline — check Ollama: `curl localhost:11434` |
| Iris card blank | Check `/api/v2/iris/status` returns `ok:true` |
| Retirement refresh stuck | Check `logs/portfolio_server.log` — alex --weekly-health takes ~60s |
| Task modal no company info | Check `watchlist_symbol_master` for symbol — company_info may be empty |
| Task modal no agent views | Check task-detail `agent_results` query — 14 day window |
| Task modal no synthesis | Check `/api/v2/watchlist/context/<symbol>` — synthesis requires CIO run |
| Task modal no technicals | Check `enrichment_cache` or `finviz_data` table for symbol data |

### Frontend Components (v5.2)

| Component | Path | Purpose |
|-----------|------|---------|
| SmartTextarea | `src/components/shared/SmartTextarea.tsx` | Spell check + mic dictation + AI rewrite (local). pageType: approval/watchlist/research/retirement |
| AddYouTubeChannelModal | `src/components/shared/AddYouTubeChannelModal.tsx` | Channel name + category + agent tags + threshold → save |
| TaskDetailDrawer | `src/components/TaskDetailDrawer.tsx` | Full intelligence panel: header, 7 P&L tiles, conflict banner, CIO synthesis, 3-col agent views, news, technicals, past decisions, SmartTextarea |
| Iris Card | `src/pages/Overview.tsx` | Coverage bar + pending proposals + Ask Iris Q&A |
| Freshness Badge | `src/pages/Retirement.tsx` | Green/amber based on data age + Refresh button |

### Additional API Endpoints (v5.3)

| Endpoint | Method | What |
|----------|--------|------|
| `/api/v2/rewrite-note` | POST | Local LLM rewrite with Claude Haiku fallback — `{text, page_type}` → `{ok, rewritten, provider}` |
| `/api/v2/rewrite-note/status` | GET | Local LLM availability — `{local_llm: bool, fallback: "claude-haiku-4-5"}` |
| `/api/v2/retirement/refresh` | POST | Trigger fresh Alex analysis in background (~60s) |
| `/api/v2/portfolio-intelligence` | GET | 47 positions with real sectors, per-account/sector P&L, cross-account, best/worst, classification |
| `/api/v2/news/articles` | GET | Paginated news — `?strategy=&source=&relevance=&search=&limit=&offset=` (14 categories, retirement_relevance) |
| `/api/v2/admin/backfill-news-strategy` | POST | Classify all news articles (idempotent — 0 on second call) |
| `/api/v2/rag/status` | GET | RAG embedding coverage per source type (10 types, 5159 total rows) |
| `/api/v2/admin/rag-backfill` | POST | Background backfill of all source types into content_embeddings |
| `/api/v2/tasks/<id>/resolve` | POST | Resolve a task — `{note}` → updates john_decision_queue status to decided_action |
| `/api/v2/tasks/<id>/defer` | POST | Defer a task — `{note}` → updates status to deferred |
| `/api/v2/tasks/<id>/reject` | POST | Reject a task — `{note}` → updates status to rejected |
| `/api/v2/tasks/deduplicate` | POST | Remove duplicate pending tasks (keeps newest per symbol+category) |

### Key Pages (v5.2)

| Page | Path | What |
|------|------|------|
| Portfolio Intelligence | `/v2/portfolio-intelligence` | Sector breakdown with P&L bars, cross-account analysis, performance rankings, full sortable/filterable position table |

### Additional Diagnostics (v5.3)

| Problem | Fix |
|---------|-----|
| Portfolio Intel shows "Unclassified" | Add symbol to ETF_MAP or DEFENSE set in `_portfolio_intelligence()` in api_v2.py |
| Unrealized % shows 0 for 401k | Fidelity doesn't export cost basis — 401k positions always show 0% |
| Cross-account shows empty | All symbols in only one account — correct if true |
| Task badge inflated (duplicates) | Run: `curl -X POST http://localhost:7777/api/v2/tasks/deduplicate` |
| Resolve/Defer/Reject not working | Check `/api/v2/tasks/<id>/resolve` — needs `{note}` in body |
| Mic blocked on HTTP | Chrome requires HTTPS — shows "Mic blocked" error in UI |
| AI rewrite empty | Local LLM may be down — check `/api/v2/rewrite-note/status`, Claude Haiku is automatic fallback |
| Nightly pipeline creates duplicate tasks | Fixed: `aegis_synthesis.py` now checks for existing pending task per symbol+category before inserting |

---

*SKILL.md v6.7 — Keyword fallback bug fixed: RealDictCursor dict→tuple conversion. LHX returns 3 items (was 0). Fallback chain: DB embeddings→YouTube→News→Brave. All 4 RAG paths verified: ticker (LHX→"LHX outcome"), symbol (SCHD→"SCHD dividend"), category:ssdi (3 YouTube), category:disability (3 YouTube). Coverage 99.7%.*
*SSH: johnclaw@192.168.50.16 — see /api/v2/system-health for live stats*
*System Bible: TRADE_AI_V12_SYSTEM_BIBLE_V3.md — check there for full detail on any section.*
