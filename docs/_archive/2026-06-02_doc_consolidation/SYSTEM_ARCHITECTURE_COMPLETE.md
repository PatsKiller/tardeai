> **ARCHIVED 2026-05-31:** Unique content consolidated into MASTER_SYSTEM_DOCUMENTATION.md. This file is no longer authoritative.

# Trade AI v12 — Complete System Architecture

**Version:** 12.30 | **Date:** 2026-05-12 | **Classification:** Internal Technical Reference

---

## 1. Design Principles

Trade AI v12 is a single-operator portfolio intelligence and paper trading system built on five architectural invariants:

1. **Human-in-the-loop execution.** No trade executes without explicit operator approval. Automation handles discovery, analysis, monitoring, and learning — but the approval gate is always human.
2. **Fail-closed safety.** Every execution path fails toward inaction, not action. If a risk gate errors, the trade is blocked. If a stop can't be placed, the position is closed. If fill verification times out, the order is canceled.
3. **Alpaca is source of truth.** The broker's position state is authoritative. The database reflects the broker, not the other way around. Phantom positions (DB-only, no broker match) are auto-detected and closed every 5 minutes.
4. **Continuous learning.** Every closed trade produces lessons that feed back into agent context via RAG embeddings, intelligence rules, and pattern validation. The system gets smarter with each trade.
5. **Defense in depth.** Risk is managed at every layer: proposal generation, risk gate, human approval, fill verification, stop placement, R-multiple trailing, negative news scanning, phantom detection, and reconciliation.

---

## 2. System Topology

```
┌─────────────────────────────────────────────────────────────────┐
│                        OPERATOR (Human)                         │
│  Telegram commands · Command Center UI · Email digest           │
└────────┬──────────────────────┬──────────────────────┬──────────┘
         │                      │                      │
    ┌────▼────┐          ┌──────▼──────┐        ┌──────▼──────┐
    │Telegram │          │ Command     │        │ GOG/Gmail   │
    │Bot      │          │ Center (UI) │        │ Digest      │
    │Handler  │          │ React 19    │        │ (daily)     │
    └────┬────┘          │ Vite 8      │        └─────────────┘
         │               │ Port 5173   │
         │               └──────┬──────┘
         │                      │
    ┌────▼──────────────────────▼──────────────────────────────┐
    │              PORTFOLIO SERVER (Port 7777)                 │
    │  api_v2.py — aiohttp — 283+ endpoints — 16,100 lines    │
    └────┬────────────┬────────────┬───────────┬───────────────┘
         │            │            │           │
    ┌────▼────┐ ┌─────▼─────┐ ┌───▼───┐ ┌────▼─────┐
    │PostgreSQL│ │  Ollama   │ │Alpaca │ │OpenClaw  │
    │333 tables│ │qwen3:14b  │ │Paper  │ │Gateway   │
    │trade_ai  │ │nomic-embed│ │Broker │ │Port 18789│
    │          │ │Port 11434 │ │       │ │4 agents  │
    └──────────┘ └───────────┘ └───────┘ └──────────┘
```

**Runtime environment:** Ubuntu Linux, Python 3.13, Node 22, systemd services, cron scheduler.

---

## 3. Component Inventory

| Component | Technology | Location | Purpose |
|-----------|-----------|----------|---------|
| Portfolio Server | Python aiohttp | Port 7777 | API gateway for all data and actions |
| Command Center | React 19 + Vite 8 | Port 5173 | 76-page operator dashboard |
| PostgreSQL | 333 tables | localhost:5432 | All persistent state |
| Ollama | qwen3:14b + nomic-embed-text | Port 11434 | Local LLM inference + embeddings |
| Alpaca Paper | REST API | paper-api.alpaca.markets | Broker execution (paper only) |
| OpenClaw Gateway | Node.js | Port 18789 | Conversational agents (Maria, Steph, Aegis, Alex) |
| Telegram Bot | Bot API | tradeai_bigjohn718_bot | Alerts, commands, approvals |
| GOG (Gmail CLI) | OAuth + CLI | ~/.local/bin/gog | Daily email digest |
| Cron Scheduler | crontab | 85+ entries | All scheduled automation |
| Alert Digest | send_alert_digest.py | 8 AM + 4 PM M-F | Three-tier alert aggregation |
| Data Gap Resolver | data_gap_resolver.py | Hourly+daily+weekly | Self-healing intelligence loop |

### External Data Providers

| Provider | Data | Refresh |
|----------|------|---------|
| Finviz Elite | Screener signals, short interest, news | 10 AM + 4 PM |
| Alpha Vantage | News sentiment, fundamentals | On demand |
| Finnhub | Catalyst alerts, SEC filings | On demand |
| Polygon | Halt detection, tick data | Real-time |
| FRED | Macro indicators (VIX, yield curve, Fed funds) | Daily |
| YouTube Data API | Transcript ingestion (48 channels) | Daily 7 PM |
| Brave Search | Web research | On demand |
| xAI/Grok | Debate/reasoning fallback LLM | On fallback |
| OpenAI | gpt-4o-mini fallback LLM | On fallback |
| Anthropic | claude-sonnet-4-6 fallback LLM | On fallback |

---

## 4. LLM Routing Architecture

All LLM calls route through `local_llm.py` → `generate()` with a toll-gate lock (`/tmp/ollama_llm_gate.lock`) serializing GPU access.

```
Request → local_llm.generate()
    │
    ├─ Try 1: Ollama (qwen3:14b, localhost:11434)
    │         9.9 tok/s on Intel Arc B50 Vulkan
    │         ~15s per agent-sized call
    │
    ├─ Try 2: OpenAI (gpt-4o-mini)
    │         30s timeout fallback
    │
    ├─ Try 3: Anthropic (claude-sonnet-4-6)
    │         Secondary cloud fallback
    │
    └─ Fail: Return empty (caller handles gracefully)
```

**Process types** control routing policy: STANDARD (general), REALTIME (time-sensitive), BATCH_OVERNIGHT (gemma3:27b for batch), EMBEDDING (nomic-embed-text), MEDIA_CONTENT, CRITICAL_CLOUD (force cloud).

**Audit trail:** Every call logged to `logs/llm_routing_audit.jsonl` with caller, model, latency_ms, status, fallback chain.

### Multi-Tier Trade Review Orchestration

Separate from the fallback chain, the trade review system uses 4 models deliberately for escalating analysis depth:

```
Trade Close Event
    ├─ Realtime (qwen3:14b) ── immediate, via on_paper_trade_closed()
    ├─ Overnight (gemma3:27b) ── 8 PM nightly, via overnight_batch.py
    ├─ Weekly (OpenAI gpt-4o) ── Sunday 10 AM, cron
    └─ Monthly (Anthropic Claude) ── 1st of month, cron
```

Each tier generates reviews with 4 agent perspectives (risk_agent, strategy_agent, execution_agent, learning_agent). Higher tiers receive lower-tier reviews as context. All reviews index findings into RAG and write learning outcomes to `agent_intelligence_rules`.

**Implemented in:** `multi_tier_trade_reviewer.py`
**Persists to:** `paper_trade_multi_reviews`, `agent_curation_events`, `content_embeddings`, `agent_intelligence_rules`

---

## 5. The Trading Pipeline — End to End

### 5.1 Discovery

Candidates enter the system through three independent discovery channels:

| Channel | Script | Schedule | Output |
|---------|--------|----------|--------|
| Finviz Screeners | `finviz_screener_runner.py` | 10 AM + 4 PM | `trade_ai_scans` |
| Social Scanner | `social_scalp_scanner.py` | Every 30 min, 6 AM–4 PM | `scalp_scan_results` |
| Pre-Market Watcher | `premarket_watcher.py` | Every 15 min, 5:30–9:30 AM | `news_articles` |

All channels converge at the `trade_ai_scans` table — the canonical candidate list.

### 5.2 Scoring (trade_ai_orchestrator.py)

A 23-stage pipeline scores each candidate on a 55-point scale across 6 pillars:

- Relative strength, volume/flow, technical indicators (RSI, SMA), trend direction, catalyst quality (verified > unverified), sector momentum.

**Output:** Each symbol receives a decision (GO / WAIT / AVOID), a grade (A+ through C), and a signal_grade. GO signals with score >= 45 advance to the agent analysis layer.

### 5.3 Multi-Agent Analysis

`process_watchlist_agent_jobs.py` routes each candidate through 4–5 independent agents:

| Agent | Role | Focus |
|-------|------|-------|
| Maria | Senior research analyst | Fundamental quality, catalyst verification, competitive position |
| Steph | Income guardian | Allocation fit, $55K income target, account placement |
| Risk Agent | Risk analyst | Technical damage, stop placement, drawdown risk |
| Tax Agent | Tax optimizer | Roth conversion impact, IRMAA threshold, lot selection |
| Full Chain | Committee synthesis | Comprehensive multi-factor review (optional) |

Each agent receives rich context injection:

```
Agent Prompt
  ├── Scan intelligence (score, RVOL, catalyst, sector)
  ├── Cross-agent views (other agents' latest recommendations)
  ├── Recent intelligence (intel summary + outcome feedback)
  ├── Sentiment + social context (news, social, fused signals)
  ├── RAG context (5 items: prior intelligence via vector search)
  ├── Research advisories (active user research findings)
  ├── Peer agent notes (30-day recommendation history)
  ├── Content gap warnings (Iris-flagged missing data)
  ├── Technical confluence (indicator agreement)
  ├── Pipeline context (which screeners surfaced this ticker)
  ├── Agent calibration (this agent's historical accuracy)
  ├── Strategy playbook (YAML-defined strategy rules)
  └── Global rules G1-G10
```

**Output:** `watchlist_agent_results` — per-agent recommendation (BUY/HOLD/AVOID/SELL), confidence (0.0–1.0), narrative, reason codes.

### 5.4 Synthesis

`aegis_synthesis.py` combines multi-agent results with technical snapshots, social sentiment, and transcript intelligence into a single recommendation per symbol.

**Output:** `watchlist_final_synthesis` — unified recommendation, confidence, synthesis narrative.

### 5.5 CIO Decision

`cio_decision_engine.py` makes portfolio-level decisions considering:

- Strategy rule evaluations, agent synthesis, fused signals, income profiles, existing portfolio weights.

**Output:** `cio_decisions` — action (HOLD/BUY/SELL/HUMAN_REVIEW/BLOCKED), priority, rationale, human_review_required flag.

### 5.6 Proposal Generation

`auto_proposal_generator.py` creates PENDING proposals for GO signals that pass quality filters:

- Entry/stop/target computed from strategy timeframe map
- Position sizing normalized: max $2,000 per position, max $150 dollar risk
- Risk-reward ratio must be >= 1.2

**Output:** `paper_trade_proposals` (status=PENDING) with full trade plan.

### 5.7 Proposal Enrichment

Proposals are enriched asynchronously before the decision gate:

| Step | Script | Output |
|------|--------|--------|
| Agent review | `queue_proposal_agent_reviews.py` | Scalp critic A–F grade |
| Intelligence analysis | `proposal_intelligence_analyzer.py` | LLM thesis assessment |
| Quality review | `proposal_quality_reviewer.py` | Data quality + conflict check |

### 5.8 Decision Gate

`proposal_decision_gate.py` computes a decision state per proposal:

| State | Meaning |
|-------|---------|
| APPROVE_READY_PAPER_TEST | Pass — ready for human approval |
| CAUTIOUS_PAPER_TEST | Low confidence but acceptable |
| RESEARCH_INCOMPLETE | Need more agent analysis |
| AI_REVIEW_MISSING | Need LLM analyst |
| DATA_STALE | Price or catalyst too old |
| BACKTEST_INSUFFICIENT | Need historical validation |
| REJECT_RECOMMENDED | Block trade |
| BLOCKED_BY_RISK_GATE | Risk gate veto (highest priority) |

### 5.9 Human Approval Gate

The operator reviews proposals via Telegram or the Command Center UI:

- Telegram: `/approve proposal <id>` or `/reject proposal <id>`
- UI: Approvals page with full context, agent votes, and risk assessment

**No trade proceeds without explicit human approval (Global Rule G10).**

### 5.10 Execution

`alpaca_paper_adapter.py` submits the approved trade to Alpaca Paper:

```
Trading Hours Gate (Mon-Fri 4:00 AM – 8:00 PM ET)
    │ BLOCKED if outside hours (weekends, overnight)
    │ Extended hours: 4:00-9:30 AM (pre-market) + 4:00-8:00 PM (after-hours)
    ▼
Risk Gate (20 checks)
    │ BLOCKED if any fail-closed gate fires
    ▼
Max Positions Check (3 concurrent max)
    │ REJECTED if at capacity
    ▼
Order Type Decision
    ├── Regular hours (9:30-16:00):
    │   ├── Market order: price at or below entry
    │   └── Bracket order: limit entry + stop + target (atomic)
    └── Extended hours (4:00-9:30, 16:00-20:00):
        └── Limit order only (Alpaca requirement), extended_hours=true
            No bracket orders, no market orders in extended hours
    │
    ▼
Submit to Alpaca API
    │
    ▼
Fill Verification Loop (8 retries, ~20 sec)
    ├── filled → record actual fill price + quantity
    ├── canceled/rejected → abort, no DB record
    ├── partially_filled → cancel + close partial → abort
    └── timeout → cancel if market order, mark pending if limit
    │
    ▼
Stop Placement (market orders + extended hours fills — brackets are atomic)
    ├── 3 retry attempts
    └── All fail → CLOSE POSITION IMMEDIATELY (fail-closed)
    │
    ▼
DB Record Created (status = 'open' only if fill verified)
    │ Notes include: order type reason, fill status, stop method
```

### 5.11 Active Monitoring

Two monitors run continuously during market hours:

**paper_trade_monitor.py — Every 5 minutes:**

| Check | Action |
|-------|--------|
| Target hit (price >= target) | Market sell, close trade, trigger curation |
| Near target (>= 80% of move) | Tighten stop to lock 65% of target move |
| R >= 3.0 | Trail stop to lock 2.0R profit |
| R >= 2.0 | Trail stop to lock 1.0R profit |
| R >= 1.5 | Trail stop to lock 0.5R profit |
| R >= 1.0 | Move stop to breakeven |
| Missing stop on Alpaca | Place stop immediately |
| Phantom position (DB open, no Alpaca match) | Auto-close with audit trail |
| Catch-up gap (>10 min since last update) | Force full re-evaluation |

Stops only move UP, never down. All adjustments executed on Alpaca via API and logged as `MONITOR_*` curation events.

**Stop replacement protocol (V2.4, 2026-05-26):** `replace_stop()` cancels the existing stop, verifies cancellation via API poll (up to 5 retries), then places new stop. Records `stop_order_id` and `stop_updated_at` on the DB row. Trailing stops above entry price are supported (constraint `chk_long_stop_below_entry` removed).

**open_trade_monitor.py — Every 15 minutes:**

| Check | Action |
|-------|--------|
| Near stop (75% of stop distance consumed) | CRITICAL alert via Telegram |
| Near target (80% of target move) | INFO alert |
| Negative news (offering, dilution, downgrade, lawsuit) | WARN alert |
| Critical news (SEC halt, bankruptcy, fraud, delisted) | **AUTO-CLOSE position** |
| Extended profit (R >= 3.0) | INFO alert |
| Stale trade (>1 hour since last price) | WARN alert |
| Volume fade | WARN alert |

**Price staleness protection:** Monitor checks `scanned_at` timestamp — if older than 5 minutes, falls back to Alpaca latest trade API.

**Reconciliation:** Hourly cron (10:00–16:00 M-F) runs `alpaca_paper_adapter.py --sync-only` to catch any DB ↔ Alpaca drift.

### 5.12 Trade Closure

Trades close through five paths:

| Path | Trigger | Script |
|------|---------|--------|
| Target hit | Price >= target_1 | paper_trade_monitor.py |
| Stop hit | Alpaca stop order executes | Alpaca broker |
| Manual close | Telegram `/ptclose` or UI button | telegram_command_handler.py |
| Phantom detection | DB open but no Alpaca position | paper_trade_monitor.py |
| Critical news | SEC halt, bankruptcy, fraud headline | open_trade_monitor.py |

### 5.13 Post-Trade Learning

`agent_curation_hooks.py` fires on every closure:

| Hook | Agent | Output |
|------|-------|--------|
| _write_outcome_to_proposal | System | Outcome provenance → `paper_trade_proposals` (verdict, pnl, r_multiple) |
| iris_record_trade_outcome | Iris | Outcome lesson → `agent_intelligence_rules` |
| aegis_write_post_trade_synthesis | Aegis | Synthesis paragraph → `agent_curation_events` |
| trigger_outcome_lessons | System | Outcome scorer → feedback loop |
| check_pattern_confirmation | Iris | Pattern library validation |
| _index_trade_outcome_to_rag | RAG | Embed outcome → `content_embeddings` (1.35x boost) |

Trade outcomes are the highest-boosted RAG source (1.35x), ensuring agents prioritize learning from real trades over news or social signals.

**Post-close processors** (async, non-blocking):
- `post_trade_thesis_reviewer.py` — Compares plan vs actual, classifies thesis outcome
- `paper_outcome_analytics.py` — Builds R-multiple, MFE/MAE, plan adherence stats

### 5.14 Feedback Loop

`feedback_loop_processor.py` runs daily to close the full learning cycle:

```
Closed Trades → proposal_outcome_chain → Agent Calibration
    │
    ├── Agent accuracy updated (confidence ±0.05 per correct/incorrect)
    ├── Strategy performance snapshots (weekly aggregation)
    ├── Pattern library win rates adjusted
    ├── Recovery watch outcome detection
    └── RAG embeddings available for next cycle's agent analysis
```

---

## 6. Risk Management

### 6.1 Risk Gate (20 Checks)

`risk_gate.py` implements 20 checks that must all pass before any trade executes:

| Gate | Check | Threshold |
|------|-------|-----------|
| GLOBAL_HALT | System-wide trading halt | Boolean control |
| LIVE_HALT | Live mode blocked | Always true (paper only) |
| STRATEGY_HALT | Per-strategy halt control | Boolean per strategy |
| STRATEGY_KILLED | Strategy registry active flag | active=true required |
| ACCOUNT_INELIGIBLE | Forbidden account/strategy combos | No scalp in IRA/401k |
| DAILY_LOSS_LIMIT_HIT | Today's losses vs limit | risk_per_trade × multiplier |
| WEEKLY_LOSS_LIMIT_HIT | 7-day losses vs limit | risk_per_trade × weekly_multiplier |
| MAX_POSITIONS_HIT | Concurrent position count | 3 per account, 8 total |
| SAME_SECTOR_EXPOSURE | Sector concentration | Max 1 per sector |
| STOP_NOT_DEFINED | Stop loss present | stop_loss > 0 required |
| STOP_TOO_WIDE | Stop distance | <= 15% from entry |
| DOLLAR_SIZE_TOO_LARGE | Position size | $15,000 paper max |
| DATA_QUALITY_LOW | Intelligence readiness | intel_readiness >= 20 |
| DATA_STALE | Data freshness | < 60 minutes |
| REGIME_PAUSED | VIX regime check | VIX >= 35 blocks; 25-35 warns |
| SOCIAL_ONLY_CATALYST | Social-sourced catalyst | Requires verified=true |
| SSDI_IRMAA | Income/disability impact | MAGI and bracket checks |
| UNKNOWN_STRATEGY | Strategy whitelist | 6 known strategies only |
| MISSING_EVIDENCE | Minimum evidence threshold | Per-strategy YAML config |
| RISK_GATE_ERROR | Exception handling | Fail-closed for execution contexts |

**Context modes:** Fail-closed for paper_trade, live_trade, approval_ready, broker_submit. Fail-open for discovery, dashboard_display.

### 6.2 Global Rules (G1–G10)

Injected into every agent prompt:

| Rule | Principle |
|------|-----------|
| G1 | Never analyze stale data. News >7d, prices >24h, SEC >30d → skip |
| G2 | Never recommend TRIM/SELL if position yield × value > $11,000/yr |
| G3 | For IRA/401k: include MAGI impact, IRMAA flag if >$103K, Medicaid lookback |
| G4 | Confidence <40% → skip. Single source → skip. Decisions >14d → expire |
| G5 | Read outcome lessons, adjust confidence ±0.05 per past result |
| G6 | Check FRED macro context. VIX >25 = elevated. T10Y2Y <0 = recession risk |
| G7 | Auto-escalate to Alex on: agent conflict, Roth conversion, income-critical |
| G10 | No direct execution. Human approval required for all trades |

### 6.3 Live Trading Gate

Six gates must ALL pass before the system can ever move to live trading:

1. ALPACA_MODE must equal "paper" (currently blocks live)
2. LIVE_TRADING_ENABLED must be explicitly true
3. policy.live_trading_allowed = true
4. validation_days >= 180 (6-month paper track record)
5. closed_trades >= minimum threshold
6. win_rate and profit_factor above minimum
7. Governance board approval required

**Current status:** All 6 gates BLOCKED. Live trading is structurally impossible.

---

## 7. Intelligence Pipeline

### 7.1 Data Ingestion

| Source | Script | Schedule | Tables |
|--------|--------|----------|--------|
| Finviz screeners | finviz_screener_runner.py | 10 AM + 4 PM | trade_ai_scans |
| News (7 sources) | news_ingestion.py | 6:30 AM + 12:30 PM | news_articles |
| Social (Reddit, StockTwits) | social_ingest.py | 6:30 AM + 12:35 PM | social_posts |
| YouTube (48 channels) | transcript_processor.py | Daily 7 PM | youtube_transcripts |
| SEC Form 4 | sec_form4_ingester.py | Daily | sec_form4 |
| FRED macro | fred_fetcher.py | Daily | fred_economic_series |

### 7.2 Enrichment

`llm_intelligence_enrichment.py` runs 5 enrichment sections daily at 7:20 AM:
- Catalyst verification, sentiment scoring, thesis extraction, entity linking, RAG indexing.

### 7.3 RAG Pipeline

`rag_indexer.py` indexes 12 source types into `content_embeddings`:

| Source Type | Boost | Content |
|-------------|-------|---------|
| trade_outcome | 1.35x | Closed trade lessons (highest priority) |
| decision_outcome | 1.30x | Past decision results |
| research_finding | 1.25x | User research topic iterations |
| agent_synthesis | 1.20x | Multi-agent synthesis narratives |
| cio_decision | 1.15x | CIO portfolio decisions |
| fused_signal | 1.10x | Cross-source signal fusion |
| agent_result | 1.05x | Individual agent analyses |
| news | 1.00x | News articles |
| youtube | 1.00x | YouTube transcripts |
| social_post | 1.00x | Social media posts |
| sec_form4 | 1.00x | Insider transactions |
| fred_series | 1.00x | Macro economic data |

**Retrieval:** `rag_retrieval.py` performs cosine similarity search with recency decay (–10% per 30 days) and source boost weighting. Falls back to keyword search if embeddings unavailable.

### 7.4 Research Advisory Pipeline

User-defined persistent research topics (created via Telegram `research <topic>`) iterate daily:

```
user_research_topics → iterate_research_topics.py (daily LLM)
    ├── RAG: indexed as research_finding (1.25x boost)
    ├── Agent prompts: injected as "Active Research Advisories" block
    ├── Morning Brief: "RESEARCH ADVISORIES" section (priority 6)
    ├── Command Center: Intelligence > Research Topics page
    ├── Telegram: iteration posted on completion
    └── Email: included in daily GOG Gmail digest
```

---

## 8. Observability

### 8.1 Alert System

`alert_dispatcher.py` provides tiered, deduplicated, fatigue-aware alerting:

| Tier | Behavior |
|------|----------|
| INFO | Dashboard only — no notification |
| ALERT | Telegram notification (rate-limited: 15/hour max) |
| URGENT | Telegram with priority flag, bypasses rate limit |

**Deduplication:** Key = `{date}:{type}:{scope}`. One alert per type per symbol per day.

**Fatigue detection:** After 3 consecutive days of the same alert, auto-downgrades from ALERT to INFO and fires a one-time meta-alert.

### 8.2 Pipeline Monitoring

`pipeline_watchdog.py` runs every 5 minutes:
- Detects missed or failed pipeline runs via `pipeline_schedule` table
- Auto-retries critical scripts (max 3 retries/day)
- Queues uncovered GO signals that have no agent analysis
- Manages stale intelligence entities

### 8.3 Morning Brief

`aegis_morning_brief_delivery.py` delivers at 8:00 AM via Telegram and markdown export:

1. Immediate risk (triggered stops, danger zone, unprotected positions)
2. Steph review queue (escalated symbols)
3. Recovery watch (stopped-out positions under review)
4. Covered call candidates
5. Rotation alternatives
6. Research advisories (top 3 research findings)
7. Next actions (prioritized punch list)

Plus: event intelligence digest, Iris taxonomy status, pipeline health, dividends, pending proposals, recovery watch summary.

### 8.4 System Health Endpoint

`GET /api/v2/system-health` returns:
- LLM status (available, model, latency)
- Database table counts (key tables)
- CIO decision distribution
- Cron job count
- Active screener count

### 8.5 Governance

`paper_performance_governance.py` tracks per-strategy:
- Closed trade count, profit factor, win rate, R-multiples
- TCA slippage, broker reconciliation issues
- Minimum thresholds: 30 trades for watchlist, 1.25 profit factor, 180 calendar days

### 8.6 Automated Journal

The "Automated Journal" tab (renamed from Paper Journal) provides the same depth as the regular journal for all automated trading accounts. Currently: Alpaca Paper. Per-trade professional execution log:

| Section | Content |
|---------|---------|
| Position Details | Shares, direction, entry, stop, target, current price, risk $, MFE, MAE, VIX, regime |
| Entry Rationale | Strategy, opened_via, catalyst (verified/unverified), risk gate result |
| Execution Log | Timeline of all MONITOR_* events, alerts, stop adjustments, system observations |
| Exit & Outcome | Exit reason, verdict (WIN/LOSS), closed_via |
| Journal Review | Mistake tags, strength tags, lesson learned, system fixes |

API: `/api/v2/automated-trade-journal?account=ALPACA_PAPER`

### 8.7 Logging

| Log | Path | Content |
|-----|------|---------|
| LLM audit | logs/llm_routing_audit.jsonl | Every LLM call with model, latency, fallback |
| Pipeline | logs/pipeline_watchdog.log | Watchdog actions and retries |
| Paper monitor | logs/paper_monitor.log | 5-min position monitoring |
| Trade monitor | logs/open_trade_monitor.log | 15-min alert monitoring |
| Alpaca adapter | logs/alpaca_paper_adapter.log | Broker sync and execution |
| System health | logs/system_health_alerts.log | Health check results (JSON) |
| Morning brief | logs/aegis_brief.log | Brief composition and delivery |

---

## 9. Execution Safety Chain

Every step in the trade lifecycle has fail-closed behavior:

| Step | Safety Gate | Fail Mode |
|------|------------|-----------|
| Proposal | Risk gate (20 checks), quality filter, sizing caps | Reject proposal |
| Submission | Market hours gate, max positions check | Block order |
| Fill | Verification loop (8 retries, ~20 sec) | Abort + no DB record |
| Stop placement | 3-retry atomic stop | Close unhedged position |
| Monitoring | 5-min R-trail, phantom detection, catch-up | Auto-adjust or close |
| News | Critical keyword scan every 15 min | Auto-close position |
| Reconciliation | Hourly DB ↔ Alpaca sync | Detect drift, trigger curation |
| Closure | Curation hooks: Iris + Aegis + RAG + patterns | Learn from outcome |

---

## 10. Incubator System

The incubator is a pre-proposal pipeline that scouts and nurtures candidates:

```
Discovery → Incubator Universe (ACTIVE)
    │
    ├── Daily refresh: update scores, catalysts, RVOL
    ├── Event detection: IMPROVED / DEGRADED / STAYED_ACTIVE
    │
    ├── LLM Screening: A-F grade → PROMOTE / HOLD / DROP
    │
    └── Promotion: Create paper_trade_proposal from graduated candidate
```

**Lifecycle:** ACTIVE → (daily refresh) → (LLM screen) → PROMOTE → paper_trade_proposals → execution pipeline.

**Graduation criteria:** 30 trades minimum, 1.25 profit factor, 180 days validation.

---

## 11. Key Database Tables by Domain

| Domain | Key Tables | Purpose |
|--------|-----------|---------|
| Discovery | trade_ai_scans, scalp_scan_results, news_articles | Candidate signals |
| Agent Analysis | watchlist_agent_results, watchlist_agent_jobs, watchlist_maturity_state | Multi-agent review |
| Synthesis | watchlist_final_synthesis, fused_signals, cio_decisions | Combined intelligence |
| Proposals | paper_trade_proposals, proposal_agent_reviews, strategy_cards | Trade plans |
| Execution | paper_trades, paper_execution_events | Broker state |
| Monitoring | open_trade_alerts, agent_curation_events | Active position management |
| Learning | agent_intelligence_rules, content_embeddings, decision_outcomes, pattern_library | Feedback loop |
| Incubator | incubator_universe, incubator_events | Pre-proposal pipeline |
| Risk | market_regime_snapshots, market_regime_indicators | Regime and risk state |
| Portfolio | holdings (via JSON), portfolio_income_goals, account_placement_rules | Portfolio context |
| Journal | journal_trade_reviews, journal_agent_coaching | Execution review |
| Governance | paper_validation_policy, governance_approvals | Live trading gates |

---

## 12. Current Operational State

| Metric | Value |
|--------|-------|
| Portfolio value | $1,192,663 |
| Open paper trades | 2 (INFU, XMTR) |
| Trading mode | Paper only (ALPACA_MODE=paper) |
| Live trading | BLOCKED (6 gates all failing) |
| Local LLM | qwen3:14b (9.4 GB VRAM, 9.9 tok/s) |
| Embedding model | nomic-embed-text (0.54 GB VRAM) |
| Database tables | 344 |
| API endpoints | 284+ |
| Command Center pages | 76 |
| Cron jobs | 152+ |
| RAG embeddings | 14,000+ |
| Agent results | 4,274 |

---

*This document is the authoritative technical reference for Trade AI v12. It supersedes all prior partial documentation. Update with each session.*
