---
name: broker-audit-deepseek-integration
overview: Complete Data Broker audit across 22 pages, 35+ alerts, and all pipeline scripts; plus DeepSeek Flash and DeepSeek v4 as PRIMARY models with current models as backups, LLM caching architecture, and comprehensive timing/frequency documentation.
todos:
  - id: registry-pages-missing
    content: Add 13 missing page entries to data_registry.yaml consumers.pages (ActiveTrader, Strategy, AgentRuntime, ResearchIntel, Hermes, Retirement, Journal, Defense, Rotation, RecIntel, Health, Consumption, RedeployDesk)
    status: pending
  - id: registry-pages-partial
    content: Complete 7 partially-declared pages with all actual endpoints (HomeHub, PortfolioHub, RiskHub, TradingHub, IntelligenceHub, ReportsHub, SystemHub)
    status: pending
  - id: registry-alerts
    content: Add 21 unregistered alert scripts to data_registry.yaml consumers.alerts
    status: pending
  - id: registry-outbound
    content: Add outbound notification channel entries (Telegram bypass, Email/SMTP/WhatsApp/Slack)
    status: pending
  - id: deepseek-flash-primary
    content: Add deepseek-flash as PRIMARY lane in llm_lane.py — gemma3:4b/12b become fallback; API key from Bitwarden deepseek_tradeai
    status: pending
  - id: deepseek-flash-core-agents
    content: Route 8 Core Operational agents through Flash (Maria, Steph, Risk, Tax, Aegis-routine, Scalp Critic) in process_watchlist_agent_jobs.py
    status: pending
  - id: deepseek-flash-hermes
    content: Route 11 Hermes Research Fleet components through Flash (all except Auto-Promote) in hermes dispatch
    status: pending
  - id: deepseek-flash-shadow
    content: Route 11 SHADOW fleet agents through Flash in critic_llm.py (default model override, gemma+OAuth as fallback)
    status: pending
  - id: deepseek-v4-core-agents
    content: Route DeepSeek v4 as PRIMARY for Alex-CIO, Aegis-synthesis, Iris-proposals in process_watchlist_agent_jobs.py
    status: pending
  - id: deepseek-v4-shadow
    content: Route DeepSeek v4 as PRIMARY for Alex-SHADOW (CIO synthesis critic) in critic_llm.py (per-agent model override)
    status: pending
  - id: llm-cache-module
    content: Create scripts/lib/llm_cache.py with SQLite-backed prompt+response caching
    status: pending
  - id: llm-cache-integrate
    content: Add cached_generate() to llm_lane.py, local_llm.py, and critic_llm.py; wrap highest-volume agent call sites
    status: pending
  - id: alerts-broker-route
    content: Route registered alerts through broker wrappers and consolidate direct Telegram senders
    status: pending
isProject: false
---

# Data Broker Audit & DeepSeek Integration Plan

## Part A: Page Audit — Broker Coverage Per Page/Tab

**177+ API endpoints** across 22 pages were audited. Only **1 page** (WatchHub) has a comprehensive, accurate registry declaration. **13 pages have zero registry entries.** Even declared pages are 67-95% incomplete.

### Pages With Zero Registry Coverage (13 pages — need full `consumers.pages` entries)

| Page | Route | Endpoints |
|------|-------|-----------|
| ActiveTraderHub | `/v3/active-trader` | 2 |
| StrategyHub | `/v3/strategy` | 9 |
| AgentRuntimeHub | `/v3/agents` | 3 |
| ResearchIntelligenceHub | `/v3/research-intelligence` | 10 |
| HermesHub | `/v3/hermes` | 15 |
| RetirementHub | `/v3/retirement` | 2 |
| JournalHub | `/v3/journal` | 12 |
| DefenseHub | `/v3/defense` | 7 |
| RotationIntelligence | `/v3/rotation` | 9 |
| RecommendationIntelligence | `/v3/rec-intel` | 5 |
| HealthHub | `/v3/health` | 7 |
| ConsumptionHub | `/v3/consumption` | 6 |
| RedeployDeskIntegrated | `/v3/redeploy` | varies |

### Pages With Partial Registry Coverage (7 pages — need endpoint-level gap fills)

| Page | Declared | Actual | Coverage |
|------|----------|--------|----------|
| HomeHub | 3 | 14+ | 21% |
| PortfolioHub | 6 | 22+ | 27% |
| RiskHub | 2 | 6 | 33% |
| TradingHub | 4 | 14+ | 28% |
| IntelligenceHub | 2 (wrong endpoints) | 2 | 0% |
| ReportsHub | 1 | 10+ | 10% |
| SystemHub | 1 | 19+ | 5% |

### Implementation: Pages

For each of the 20 undeclared/incomplete pages, add a `consumers.pages` entry to `config/data_registry.yaml` listing every API endpoint called, with the correct `data_type` (existing or new) and `broker` flag. Reference implementation: the WatchHub entry (16 reads, 15 broker:true). This is configuration-only work — no code changes needed for the registry entries themselves.

---

## Part B: Alert Audit — 35 Scripts, 21 Unregistered

### Registered Alert Broker Coverage

| # | Alert | Data Reads | Broker? |
|---|---|---|---|
| 1 | Position/stop alerts | RSI/ATR/SMA local recompute, analyst direct SQL | **Partial** (quote: yes, indicators: no) |
| 2 | Proposal/ATM alerts | get_best_quote for price; proposal data direct SQL | **Partial** |
| 3 | Watch/re-entry alerts | market_quotes direct, RSI from stale column | **Partial** |
| 4 | Watchlist entry planner | Now uses broker for RSI/ATR/analyst, but research cards + synthesis direct SQL | **Partial** |
| 5 | Pullback MACD screener | All indicators locally recomputed | **No** |
| 6 | Holdings gain guardian | 4 data types bypass broker ("worst offender") | **Partial** |
| 7 | Portfolio live monitor | Finviz scrape + buggy MACD | **No** |
| 8 | Ask alerts | quote: broker, news: direct SQL | **Partial** |
| 9 | IPO lockup alert | broker for price, config for lockups | **Yes** |
| 10 | Open trade monitor | get_best_quote + own Alpaca fallback | **Partial** |
| 11 | Screener/social alerts | Independent catalyst verification | **No** |
| 12 | Hermes/research alerts | Direct SQL on hermes tables | **Partial** |
| 13 | Global alerts banner | JSON files only | **No** |
| 14 | Premarket catalyst alerts | Direct Finviz API + SQL | **No** |

### Unregistered Alert Scripts (21 scripts — no registry entry at all)

`system_health_alerts.py`, `protection_alerts.py`, `stop_drift_alert.py`, `eod_open_trade_alert.py`, `send_watchpool_maturity_alerts.py`, `telegram_smart_alerts.py`, `run_atp_alert_evaluator.py`, `send_screener_schedule_health_alert.py`, `send_no_leads_diagnostic_alert.py`, `alert_dispatcher_unified.py`, `portfolio_alerts.py`, `overnight_digest_telegram.py`, `pipeline_alert.py`, `scalp_alert_emitter.py`, `premarket_watcher.py`, `check_llm_fleet_alerts.py`, `report_alert_sla_status.py`, `proposal_alerter.py`, `siem_critical_notify.py`, `alerting.py`, `options_lifecycle_alerts.py`

### Outbound Channel Issue

~10 alert scripts bypass the central `telegram_alert.send_telegram` chokepoint and send via direct `requests.post` to the Telegram API. Additional outbound channels (Email via GoG CLI, SMTP, WhatsApp formatting, Slack formatting) are not tracked in the registry.

### Implementation: Alerts

**Phase 1 (Registry):** Add all 21 unregistered alert scripts to `config/data_registry.yaml:consumers.alerts` with correct `data_type` and `broker` flags.

**Phase 2 (Broker routing):** Route the 14 registered alerts through broker wrappers where applicable (highest ROI: holdings_gain_guardian for RSI/ATR/SMA, pullback_macd_screener for MACD, portfolio_live_monitor for all four bypassed types).

**Phase 3 (Outbound chokepoint):** Consolidate 10+ direct Telegram senders through `telegram_alert.send_telegram` or add a `notification_channel` registry entry to track all outbound channels.

---

## Part C: LLM Model Inventory — Timing & Frequency Documentation

### Bitwarden API Key

DeepSeek API key stored in Bitwarden as **`deepseek_tradeai`**. Never read or print the resolved value. Reference the key name in env config only. Follow the same pattern as other secrets: `${DEEPSEEK_API_KEY}` read from tmpfs env at `/run/user/$(id -u)/tradeai/env`.

### Currently Active Models

| Type | Model | Scripts | Daily Calls | Purpose |
|------|-------|---------|-------------|---------|
| **Local Ollama** | gemma3:4b | ~40+ scripts | ~500-1000 | Fast classification, agent analysis, general-purpose local |
| **Local Ollama** | gemma3:12b | overnight batch | ~100-200 | Quality analysis, holdings health, deep overnight |
| **Local Ollama** | gemma3:27b | monthly advisory | ~1/month | Fiduciary monthly advisory |
| **Free OAuth** | grok-3-mini (:8645) | ~20+ scripts | ~200-400 | Primary cloud — CIO synthesis, entry planning, inference |
| **Free OAuth** | gpt-5.4 (:8646) | ~10+ scripts | ~30-80 | Dual-consensus partner, cloud review, reports |
| **Paid API** | claude-sonnet-4-6 | escalation only | ~1-5 | Fallback when local + both OAuth are down |
| **Paid API** | gpt-4o | fallback only | ~0-2 | Ollama-absent fallback |

### Comprehensive Timing & Frequency Table

This maps every LLM call in the system to its trigger mechanism, cadence, and time-of-day constraints.

| Model | Trigger Mechanism | Cadence | RTH Only? | Overnight? | Hours Blocked | Typical Duration Per Call | Peak Concurrency |
|-------|-------------------|---------|-----------|------------|---------------|--------------------------|-----------------|
| **gemma3:4b** (local) | `local_llm.generate()` — called from 40+ scripts | **Continuous** — every agent job (15-min poll), every enrichment cycle, catalyst checks, health checks | No (24/7) | Yes | None | 25-30s timeout | File-lock-gated to 1 at a time (single GPU) |
| **gemma3:12b** (local) | `run_deep_overnight_llm_queue.py` (systemd timer), `holdings_llm_refresh.py` (crontab), `ci_synthesis` fallback | **Overnight batch**: 22:00-03:00 (~100+ jobs). **Weekly**: holdings health. **Monthly**: advisory | No | Yes (primary) | **BLOCKED 06:00-12:00 ET** (market hours — preserves GPU for gemma3:4b) | 60-120s per job | Sequential (single GPU); memory contention with 4b |
| **gemma3:27b** (local, heavy) | `monthly_advisory.py` (`FIDUCIARY_MODEL`) | **Monthly** — 1st of month | No | Yes | **BLOCKED during market hours** | 180-300s | Exclusive GPU lock (blocks all other local calls) |
| **grok-3-mini** (OAuth :8645) | `llm_lane.generate(lane="grok")` — inference engine, CIO synthesis, entry planner, stop reviews, ensemble votes | **Inference cycles**: every 15-30 min (~10 calls/cycle). **CIO synthesis**: on Maria Priority trigger (~30-80/day). **Entry plans**: per-candidate (up to 400/weekend). **Stop reviews**: per held symbol. **Ensemble**: per inference layer | RTH-heavy | Light (overnight batch runs use local) | None (always available via proxy) | 15-60s per call | Up to 600/day cap (T0 budget limit) |
| **gpt-5.4** (OAuth :8646) | `llm_lane.generate(lane="chatgpt")` — dual-consensus, cloud reviews, report editing, ensemble votes | **Dual-consensus**: sync with grok per CIO synthesis (~30-80/day). **Cloud review**: per escalation event. **Reports**: weekly/monthly. **Ensemble**: 3-5/min in batches | RHT-heavy | Rare | None (always available via proxy) | 20-45s per call | ~40/day cap (`CIO_DUAL_CHATGPT_CAP`); keepalive pings every 10 min |
| **claude-sonnet-4-6** (paid Anthropic API) | `local_llm.py` fallback tier 2, `hermes_external_researcher.py` (escalation), `claude_escalation_handler.py` (Claude Code CLI) | **Extremely rare** — only when local OAuth + both OAuth lanes are simultaneously unavailable | Any | Any | None | 30-90s | 1-5/day max; $3/M token cost |
| **gpt-4o** (paid OpenAI API) | `local_llm.py` fallback tier 1, `alex_hygiene.py` (direct) | **Rare** — only when Ollama is unavailable and OAuth is down | Any | Any | None | 15-45s | 0-2/day max |
| **nomic-embed-text** (local embedding) | `rag_indexer.py`, `prefetch_hybrid_rag_context.py` | **Continuous** — indexed with every agent result write; overnight queue batch indexing | No (24/7) | Yes | None | <5s per embedding | Sequential (same GPU) |

### Model Call Distribution by Time of Day

```
                     gemma3:4b  gemma3:12b  grok-3-mini  gpt-5.4  claude  embed
04:00-06:00 ET       ████████░░  ░░░░░░░░░░  ░░░░░░░░░░   ░░░░░░  ░░░░░░  ████░░░░░░
06:00-09:30 ET       ██████████  BLOCKED░░░  ░░░░░░░░░░   ░░░░░░  ░░░░░░  ████████░░
09:30-12:00 ET       ██████████  BLOCKED░░░  ██████████   ██████  ░░░░░░  ██████████
12:00-16:00 ET       ██████████  ██░░░░░░░░  ██████████   ██████  ░░░░░░  ██████████
16:00-22:00 ET       ████████░░  ░░░░░░░░░░  ████░░░░░░   ░░░░░░  ░░░░░░  ████░░░░░░
22:00-04:00 ET       ██████░░░░  ██████████  ░░░░░░░░░░   ░░░░░░  ░░░░░░  ██████████
```

### Key Cadence Triggers

| Trigger | Frequency | Models Used | Notes |
|---------|-----------|-------------|-------|
| `process_watchlist_agent_jobs.py` polling | Every 15 min | gemma3:4b (agents), grok-3-mini (synthesis), gpt-5.4 (dual-consensus) | Caps at 5 new symbols/cycle, 50-job backlog guard |
| `inference_layers.yaml` inference engine | Every 15-30 min (configurable) | grok-3-mini (primary), ensemble may add gpt-5.4 | ~10 calls per cycle; uses `inference_hermes_query.py` |
| `watchlist_entry_planner.py` | Weekly drain with catalyst override; on-demand | gemma3:4b or grok-3-mini (buy-rated upgrade) | Per-symbol, 30-120s stalls; up to 400 candidates drained on weekend runs |
| `catalyst_classifier.py` | On each news article ingest (3x daily + continuous RSS) | gemma3:4b | Per-article classification |
| `agent_watchlist_engine.py --daily` | **Nightly** (01:00 ET) | gemma3:4b (promote/propose/discovery), grok-3-mini (debate) | 6 jobs: promote, propose, discovery, rotate, health, autonomy-summary |
| `holdings_llm_refresh.py` | **Nightly** (02:00 ET) | gemma3:12b (or 4b with env override) | Full portfolio health assessment |
| `run_deep_overnight_llm_queue.py` | **Overnight** (22:00-03:00 ET, systemd timer) | gemma3:12b (100+ jobs) | Deep batch: per-symbol agent synthesis re-runs |
| `inference_ensemble.py` | Per inference cycle | grok-3-mini + gpt-5.4 | Multi-model voting for confidence scoring |
| `grok_stop_review.py` | Per held position, on stop lifecyle events | grok-3-mini | Stop curation for profit-protection |
| `grok_execution_review.py` | Per execution fill | grok-3-mini | Execution quality coaching |
| `overnight_digest_telegram.py` | **Nightly** (22:00 ET) | grok-3-mini (dashboard generation) | Telegram digest of day's activity |
| `monthly_advisory.py` | **Monthly** (1st, 01:00 ET) | gemma3:27b (fiduciary), gpt-4o (paid fallback) | Full portfolio fiduciary review |
| `claude_escalation_handler.py` | On health-agent Tier 2 trigger | claude-sonnet-4-6 (via Claude Code CLI) | Rare — only when all other lanes fail |
| OAuth lane keepalive | Every 10 min (crontab) | Light ping (no full generation) | Keeps Grok/ChatGPT OAuth tokens from expiring |

### OAuth Proxy Setup (Confirmed)

- **Grok**: `scripts/grok_oauth_proxy.py` on `:8645`, default model `grok-3-mini`, hermes CLI `--provider xai-oauth`
- **ChatGPT**: `scripts/chatgpt_oauth_proxy.py` on `:8646`, default model `gpt-5.4`, hermes CLI `--provider openai-codex`
- **Keepalive**: `scripts/oauth_lane_keepalive.py` (cron, sends real pings that roll tokens forward)
- Both expose OpenAI-compatible `/v1/chat/completions` endpoints

### Existing DeepSeek References: None

Zero DeepSeek references in any script, config, or env var. Greenfield addition.

---

## Part C-2: Agent-Level LLM Audit — 38 Agents, Current Models, DeepSeek Mapping

### Overview

Three distinct agent layers exist:

- **A. Core Operational Agents (10)** — Watchlist/portfolio analyst fleet, run by `process_watchlist_agent_jobs.py` every 15 min
- **B. Lane D SHADOW/Reflective Agents (16)** — Governed agentic runtime critics, invoked via systemd timers, advisory-only
- **C. Hermes Research Fleet (12)** — Near-24/7 research desk, coordinated by Chief Hermes Coordinator every 15 min

---

### A. Core Operational Agents (10 agents — every 15 min via `process_watchlist_agent_jobs.py`)

| # | Agent | Role | Current LLM | Frequency | DeepSeek Rec. | Rationale |
|---|-------|------|-------------|-----------|---------------|-----------|
| 1 | **Maria** | Market research — catalyst verification, fundamentals, news/social sentiment, ETF comparison, analyst ratings | gemma3:12b (local); Maria Priority tier: grok-3-mini + gpt-5.4 dual-pass (80/day cap) | Every 15 min (market hours, 10 jobs/run) | **Flash** (primary) | High-volume research synthesis. Flash handles catalyst verification + fundamentals at ~$0.27/M tokens vs free OAuth's rate limits. Dual OAuth becomes fallback only. |
| 2 | **Steph** | Portfolio allocation — income guardian, position sizing, rebalance targets | gemma3:12b (local); no OAuth lane access (policy: local-only) | Every 15 min | **Flash** (primary) | Currently local-only by policy. Flash at API level gives better quality than local gemma3:12b for allocation math, still cheap. Fallback: gemma3:4b |
| 3 | **Risk Agent** | Stop coverage, portfolio heat, risk-gate validation, drawdown checks | gemma3:12b (local-only, no cloud lanes) | Every 15 min (+ */3 min stop surveillance via `risk_gate.py`) | **Flash** (primary) | Risk assessment benefits from API reliability over local GPU contention. Fallback: gemma3:4b |
| 4 | **Tax Agent** | Tax optimization, Roth conversion, wash-sale detection, IRMAA | gemma3:12b (local) | Every 15 min | **Flash** (primary) | Tax math is deterministic enough for Flash; local gemma is overkill. Fallback: gemma3:4b |
| 5 | **Alex (CIO)** | CIO escalation arbiter, strategic oversight, retirement planning, SSDI optimization | gemma3:12b (local); grok-3-mini + gpt-5.4 dual-consensus (CIO synthesis); claude-sonnet-4-6 (escalation metered) | 5:00 AM daily scan; 7:15 AM hygiene; 8:00 AM Sun weekly; Monthly 1st; On-demand escalation | **v4** (primary CIO lane) | The highest-stakes agent. v4 replaces the grok+gpt dual-consensus pattern with a single high-reasoning arbiter. Claude escalation becomes fallback. |
| 6 | **Aegis** | Overnight surveillance, morning briefs, covered call eval, social sentiment, transcript discovery, synthesis, stop integrity | qwen3:14b / gemma3:27b (local overnight deep analysis) | 8:00 PM overnight, 8:00 AM scan, 11AM+3PM social, 9AM transcripts, 7PM ingestion, 9PM synthesis, 8:05 AM morning brief | **Flash** (primary for all non-CIO tasks); **v4** (for synthesis/brief generation) | Aegis has both routine classification (social sentiment, transcripts) and synthesis work. Flash for the former, v4 for synthesis/brief quality. |
| 7 | **Iris** | Taxonomy intelligence — content coverage, channel curation, RAG QA, gap analysis | qwen3:14b (local); claude-sonnet-4-6 (high-stakes classification); grok+gpt+local (multi-model consensus proposals) | Weekly Sun 10AM scan; Daily 7AM gap scan; Daily 7:55AM hygiene | **Flash** (primary for daily scans); **v4** (for multi-model consensus proposals) | Routine taxonomy classification → Flash. Proposal consensus (currently 3-model) → v4 as replacement for the claude lane. |
| 8 | **Social Scalp** | Social mention aggregation, scalp candidate scoring | Rules-based (deterministic, no LLM at scan stage) | Pre-market 4AM M-F; */30 min social monitoring during RTH | **None** (deterministic) | No LLM usage — rules-based scoring. Keep as is. |
| 9 | **Scalp Critic** | Post-scan catalyst validation / signal gating | qwen3:14b (local) | Event-driven (follows Social Scalp) | **Flash** (primary) | Catalyst validation is classification-quality work. Flash handles it well. |
| 10 | **Orchestrator** | Multi-agent routing, ambiguous request handling | None (deterministic keyword matching) | On-demand (Telegram/WhatsApp command) | **None** (deterministic) | No LLM usage — keyword routing. Keep as is. |

---

### B. Lane D SHADOW/Reflective Agent Fleet (16 agents — systemd-timer governed)

All SHADOW agents share the same LLM routing via `scripts/agent_runtime/critic_llm.py`:
- **Default**: `gemma3:4b` (Ollama `:11434`, overridable via `AGENT_RUNTIME_SHADOW_MODEL` env var)
- **Escalation**: grok-3-mini → gpt-5.4 → gemma fallback (when `AGENT_RUNTIME_CRITIC_LANES=1`)
- **Deterministic-only**: when lanes are off (the default)

| # | Agent | Role | Current LLM | Max Calls | Frequency | DeepSeek Rec. | Rationale |
|---|-------|------|-------------|-----------|-----------|---------------|-----------|
| 11 | **Sentinel** | Decision-integrity critic — challenges Watch artifacts for contradictions, missing evidence | gemma3:4b / grok escalation | 3 | Event-driven + 15-min drain | **Flash** (primary) | Medium-complexity review. Flash is faster and more reliable than gemma3:4b for contradiction detection. The grok escalation becomes fallback. |
| 12 | **Darwin** | Outcome-join and artifact scorer — deterministic scoring, calibration drift | None (deterministic) | 0 | 60-min sweep | **None** | Zero model calls. Keep as is. |
| 13 | **Iris (SHADOW)** | Knowledge curation — reviews provenance of candidate lessons, finds contradictions | gemma3:4b / grok escalation | 3 | Event-driven + 5-min drain | **Flash** (primary) | Same pattern as Sentinel. Flash for lesson provenance review. |
| 14 | **Reflection** | Case-to-lesson and hypothesis-candidate generation from completed cases | gemma3:4b / grok | 3 | Nightly Mon-Fri 9:30PM | **Flash** (primary) | Nightly batch generation — perfect for Flash's cost profile. No real-time constraints. |
| 15 | **Argus** | Population-integrity scanner — cross-artifact contradiction/drift detection | None (deterministic) | 0 | 30-min sweep | **None** | Zero model calls. Keep as is. |
| 16 | **Maria (SHADOW)** | Evidence-bound fundamental and catalyst research critic (advisory) | gemma3:4b / grok | 3 | Event-driven + 5-min drain | **Flash** (primary) | Research criticism. Flash quality exceeds gemma3:4b for evidence review. |
| 17 | **Vega** | Technical-structure review critic — levels, indicators, regime | gemma3:4b / grok | 3 | Event-driven + 5-min drain | **Flash** (primary) | Technical review is structured enough for Flash. Better than local gemma. |
| 18 | **Guardian Risk (SHADOW)** | Risk evidence critic — exposure, concentration, stop coverage | gemma3:4b / grok | 2 | 30-min sweep | **Flash** (primary) | Risk analysis benefits from consistent API quality. |
| 19 | **Aegis (SHADOW)** | Incident-review and remediation-proposal critic | gemma3:4b / grok | 3 | Event-driven + 5-min drain | **Flash** (primary) | Postmortem drafting. Flash quality is sufficient. |
| 20 | **Alex (SHADOW)** | CIO synthesis critic — synthesizes unresolved trade-offs | gemma3:4b / grok | 2 | Event-driven + 5-min drain | **v4** (primary) | CIO-level synthesis critic. Even though advisory-only, this is reasoning-heavy work. v4 is warranted. |
| 21 | **Atlas** | Durable workflow orchestration critic — coordinates bounded multi-step workflows | None (deterministic) | 0 | 15-min sweep | **None** | Zero model calls. Keep as is. |
| 22 | **Concierge** | Governed OpenClaw operator interface — read-only status/explain/cancel/replay | None (deterministic) | 0 | 5-min sweep | **None** | Zero model calls. Keep as is. |
| 23 | **Hermes (SHADOW)** | Hypothesis discovery and experiment design — anomaly discovery, preregistration | gemma3:4b / grok | 3 | Event-driven + 5-min drain | **Flash** (primary) | Hypothesis generation is creative but not CIO-critical. Flash handles it. |
| 24 | **Pulse** | Moomoo microstructure interpretation critic | gemma3:4b / grok | 2 | Event-driven + 5-min drain | **Flash** (primary) | Microstructure interpretation. Flash quality exceeds local gemma. |
| 25 | **Steph (SHADOW)** | Portfolio allocation critic — reviews allocation evidence | gemma3:4b / grok | 2 | Weekday 4:45PM | **Flash** (primary) | End-of-day sweep. Flash is reliable and cheap for allocation review. |
| 26 | **Tax Agent (SHADOW)** | Tax, wash-sale, account constraint critic | gemma3:4b / grok | 2 | Weekday 5:00PM | **Flash** (primary) | Tax review is deterministic enough for Flash. |

---

### C. Hermes Research Fleet (12 components — Chief Coordinator every 15 min)

| # | Component | Purpose | Trigger | Current LLM | DeepSeek Rec. | Rationale |
|---|-----------|---------|---------|-------------|---------------|-----------|
| 27 | **Chief Coordinator** | Orchestrate fleet, enforce per-tick caps, route tasks, auto-promote | */15 min cron, flock-guarded | gemma3:4b (local) | **Flash** (primary) | High-frequency coordinator. Needs reliable API, not local GPU contention. |
| 28 | **Autonomous Loop** | Ticker-thesis challenge + pipeline-quality validation | Via Coordinator | gemma3:12b | **Flash** (primary) | Pipeline quality validation. Flash is good enough. |
| 29 | **Source Discovery** | Discover sources via SearXNG, stage candidates | Via Coordinator | gemma3:12b | **Flash** (primary) | Discovery/classification. Perfect Flash use case. |
| 30 | **Librarian** | Review staged findings, route to embed/promote/backlog | Via Coordinator (cap 10/tick) | gemma3:12b | **Flash** (primary) | Triage/routing. Flash handles this well. |
| 31 | **Embedding Curator** | Select high-confidence research for RAG | Via Coordinator (cap 2/tick) | gemma3:12b | **Flash** (primary) | Curation/selection. Flash quality is sufficient. |
| 32 | **Auto-Promote** | Staged → promoted (bounded, reversible) | Via Coordinator (cap 10/tick) | Rules-based | **None** (deterministic) | Rules-based. Keep as is. |
| 33 | **Source Curation** | Track source yield, update registry | Weekly Sun 11:30PM cron | gemma3:12b | **Flash** (primary) | Weekly batch. Low urgency, Flash is fine. |
| 34 | **Catalyst Momentum Engine** | Catalyst-driven momentum/scalp research via SearXNG, 3 bands (premarket */30 4-9AM, swing :30 9AM-3PM, overnight 6PM/10PM) | Cron, 3 cadence bands | gemma3:12b | **Flash** (primary) | High-frequency catalyst research across 3 bands. Flash's reliability beats local gemma. |
| 35 | **Backlog Manager** | Structured research backlog | Via Coordinator | gemma3:12b | **Flash** (primary) | Backlog management. Flash works. |
| 36 | **RSS Ingest** | Parse RSS feeds, stage items | Manual | gemma3:12b | **Flash** (primary) | RSS processing. Flash handles it. |
| 37 | **Backlog Health Check** | Read-only backlog health report | Manual | gemma3:12b | **Flash** (primary) | Health report generation. Flash is fine. |
| 38 | **Embedding Promotion Reviewer** | Dry-run embed/promote recommendations | Manual | gemma3:12b | **Flash** (primary) | Review recommendations. Flash works. |

---

### Agent DeepSeek Mapping Summary

| Category | Count | DeepSeek Flash | DeepSeek v4 | No LLM Change |
|----------|-------|---------------|-------------|---------------|
| Core Operational (A) | 10 | 6 (Maria, Steph, Risk, Tax, Aegis-routine, Scalp Critic) | 2 (Alex-CIO, Aegis-synthesis, Iris-proposals) | 2 (Social Scalp, Orchestrator) |
| SHADOW Fleet (B) | 16 | 11 (Sentinel, Iris-SHADOW, Reflection, Maria-SHADOW, Vega, Risk-SHADOW, Aegis-SHADOW, Hermes-SHADOW, Pulse, Steph-SHADOW, Tax-SHADOW) | 1 (Alex-SHADOW) | 4 (Darwin, Argus, Atlas, Concierge) |
| Hermes Fleet (C) | 12 | 11 (all except Auto-Promote) | 0 | 1 (Auto-Promote) |
| **Total** | **38** | **28** (74%) | **3** (8%) | **7** (18%) |

**Key finding**: 31 of 38 agents (82%) should move to DeepSeek. Only 7 agents remain unchanged (5 deterministic, 2 rules-based).

### System Timer Architecture (SHADOW Fleet)

| Timer | Frequency | Units | Purpose |
|-------|-----------|-------|---------|
| Producer timer | Every 2 min (30s jitter) | 1 | Scans 6 trigger sources, creates drain packets |
| Per-agent drain timer | Every 15 min (120s jitter) | 16 | Drains each agent's packet queue (max 8/packet) |
| Health monitor | Every 5 min | 1 | Fleet health, stuck-packet detection |

### Per-Agent Schedule Summary

| Agent | Drain Mode | Frequency |
|-------|-----------|-----------|
| Sentinel, Iris-SHADOW, Maria-SHADOW, Vega, Aegis-SHADOW, Alex-SHADOW, Hermes-SHADOW, Pulse, Concierge | EVENT_PRIMARY | 5-15 min drain |
| Darwin | SWEEP | 60 min |
| Argus, Guardian Risk-SHADOW | SWEEP | 30 min |
| Atlas | SWEEP | 15 min |
| Reflection | NIGHTLY | Mon-Fri 9:30PM |
| Steph-SHADOW | WEEKDAY | Mon-Fri 4:45PM |
| Tax-SHADOW | WEEKDAY | Mon-Fri 5:00PM |

---

## Part D: DeepSeek Flash — PRIMARY Model, Current Models as Backup

**DeepSeek Flash** is fast, cheap (~$0.27/M tokens), and always available via API. It becomes the **PRIMARY** model for all research, synthesis, classification, and agent analysis. Current models (gemma3:4b, gemma3:12b, grok-3-mini for non-CIO) become **FALLBACK** lanes.

**Bitwarden key**: `deepseek_tradeai` — this is the API key name in Bitwarden. The env var exposed at runtime is `DEEPSEEK_API_KEY` (read from tmpfs `/run/user/$(id -u)/tradeai/env`). Never print or resolve the secret value.

### DeepSeek Flash as PRIMARY (with fallback chain)

| Task | **Primary Model** | **Fallback 1** (if DeepSeek down) | **Fallback 2** (if both down) | Scripts Affected |
|------|-------------------|----------------------------------|------------------------------|-----------------|
| Agent analysis (Maria/Steph/Risk) | **DeepSeek Flash** | gemma3:4b (local) | gpt-5.4 (OAuth) | `process_watchlist_agent_jobs.py` |
| Catalyst classification, news tagging | **DeepSeek Flash** | gemma3:4b (local) | — | `catalyst_classifier.py`, `hermes_tag_engine.py` |
| L1-L3 whiteboard curation | **DeepSeek Flash** | gemma3:4b (local) | — | `agent_watchlist_engine.py` |
| General-purpose local LLM (40+ scripts) | **DeepSeek Flash** | gemma3:4b (local) | — | `local_llm.py` default |
| Holdings health, overnight batch | **DeepSeek Flash** | gemma3:12b (local) | — | `holdings_llm_refresh.py`, `trade_strategy_classifier.py` |
| Stop curation, execution coaching | **DeepSeek Flash** | grok-3-mini (OAuth) | — | `grok_stop_review.py`, `grok_execution_review.py` |
| Entry planning | **DeepSeek Flash** | grok-3-mini (OAuth) | gemma3:4b (local) | `watchlist_entry_planner.py` |
| Report editing, Q&A narration | **DeepSeek Flash** | gpt-5.4 (OAuth) | — | `portfolio_ask.py`, `journal_ask.py`, `portfolio_monthly_report.py`, `portfolio_weekly_report.py` |

### Implementation Steps

1. Add `deepseek-flash` lane to `scripts/llm_lane.py` (OpenAI-compatible API, model: `deepseek-chat`, API key from Bitwarden `deepseek_tradeai`)
2. Set Flash as the **DEFAULT** lane in `llm_lane.py.generate()` — replace current `local` default
3. Add to `config/secret_registry.yaml`: `deepseek_api_key` entry with Bitwarden key name `deepseek_tradeai`, rotation policy standard
4. Add `deepseek-flash` to `config/hermes_research_budget.yaml` lanes + daily caps (recommend: 2000 calls/day for Flash given its low cost)
5. Add `deepseek-flash` to `config/llm_process_registry.json` process IDs (new process types: `deepseek_flash_primary`, `deepseek_flash_agent_analysis`, etc.)
6. Modify `scripts/local_llm.py` fallback chain: Primary = DeepSeek Flash → Fallback 1 = gemma3:4b → Fallback 2 = grok-3-mini (remove or gate paid Anthropic/OpenAI)
7. Route agent analyses (Maria/Steph/Risk) through DeepSeek Flash in `process_watchlist_agent_jobs.py`
8. Route L1-L3 curation through Flash in `agent_watchlist_engine.py`
9. Add to `scripts/lib/oauth_lane_status.py` health checks
10. Add to `scripts/oauth_lane_keepalive.py` (light API ping for liveness, not OAuth token roll)

---

## Part E: DeepSeek v4 — PRIMARY for CIO, Current Models as Backup

**DeepSeek v4** is the high-reasoning model (~$0.55/M tokens, vs $3/M for Claude). It becomes the **PRIMARY** model for CIO synthesis, dual-consensus arbitration, escalation handling, and ensemble heavyweight judging. Current models (grok-3-mini for CIO, gpt-5.4 for dual-consensus, claude-sonnet-4-6 for escalation) become **BACKUP/FALLBACK** lanes.

### DeepSeek v4 as PRIMARY (with fallback chain)

| Task | **Primary Model** | **Fallback** (if v4 down) | Scripts Affected |
|------|-------------------|--------------------------|-----------------|
| CIO dual-consensus synthesis | **DeepSeek v4** (sole arbiter) | grok-3-mini + gpt-5.4 (original dual-consensus pattern) | `process_watchlist_agent_jobs.py` (`_synthesis_dual`) |
| Escalation handler (health agent Tier 2) | **DeepSeek v4** | claude-sonnet-4-6 (Claude Code CLI) | `claude_escalation_handler.py` |
| External researcher | **DeepSeek v4** | claude-sonnet-4-6 | `hermes_external_researcher.py` |
| Ensemble heavyweight judge | **DeepSeek v4** (4th lane) | grok-3-mini (3rd lane only) | `inference_ensemble.py`, `config/inference_layers.yaml` |
| "Break glass" critical decision tier | **DeepSeek v4** | — (no fallback needed) | `config/hermes_research_budget.yaml` |
| Dual-consensus when grok/gpt disagree (~30-40% of the time) | **DeepSeek v4** (tie-breaking arbiter) | — (operator review) | `cloud_consensus_verdict.py`, `rerun_cio_dual_consensus.py` |

### Implementation Steps

1. Add `deepseek-v4` lane to `scripts/llm_lane.py` (model: `deepseek-reasoner`, same `deepseek_tradeai` API key from Bitwarden)
2. Set v4 as the **CIO_DEFAULT** lane — modify `_synthesis_dual()` in `process_watchlist_agent_jobs.py` to call v4 first, fall back to grok+gpt dual-consensus only if v4 is unavailable
3. Add to `config/hermes_research_budget.yaml` (new `lanes.reasoning_api` category, low daily cap: 30-50 calls/day for v4 given its reasoning cost profile)
4. Add to `config/llm_process_registry.json`: `deepseek_v4_cio_arbiter`, `deepseek_v4_escalation` process IDs
5. Add to `config/claude_escalation_allowlist.yaml` as PRIMARY escalation lane (Claude becomes backup)
6. Add v4 as 4th ensemble lane in `inference_ensemble.py` and `config/inference_layers.yaml` ensemble block
7. Replace Claude Code CLI path in `claude_escalation_handler.py` — v4 as primary, Claude as legacy fallback
8. Remove paid Anthropic/OpenAI fallbacks from `local_llm.py` — gate behind `ALLOW_PAID_FALLBACK=true` env var (default: false)
9. Modify `hermes_external_researcher.py`: change `DEFAULT_MODEL` from `claude-sonnet-4-6` to `deepseek-reasoner`

---

## Part F: DeepSeek Caching Architecture — "Curated Messages" Approach

### Concept

Store **prompt+response** pairs in SQLite, keyed by content hash, with per-tier TTLs. Only reuse when: exact prompt hash match, TTL not expired, model version same, data freshness unchanged. This is critical for DeepSeek because the API is metered (vs. free OAuth) — every cached hit saves real cost.

### New Files

- **`scripts/lib/llm_cache.py`** — Core module: `llm_cache_get(prompt_hash, model)` → response | None, `llm_cache_put(prompt_hash, model, response, ttl_hours, metadata)`, `llm_cache_invalidate_symbol(symbol)`
- **Database**: `data/runtime/llm_cache.sqlite` — single SQLite file, no server needed

### Cache Tiers

| Tier | What | TTL | Max Entries | Justification |
|------|------|-----|-------------|---------------|
| Deterministic context | Same symbol + same RSI/SMA/price/analyst input | 15 min | 5,000 | Data doesn't change within 15-min window; re-calling is waste |
| Research summaries | Same news snapshot for a symbol | 1 hour | 2,000 | News ingestion runs on cadence; between runs input identical |
| Entry plans | Same symbol with price/RSI within tolerance | 30 min | 1,000 | Highest rate-limit risk from per-symbol re-computation |
| CIO synthesis | Same symbol + same data snapshot | 2 hours | 500 | Most expensive calls (now DeepSeek v4) — highest ROI |
| Catalyst classification | Same news article | 24 hours | 10,000 | Articles don't change; classification stable |

### DeepSeek-Specific Cache Optimizations

Since DeepSeek has a context caching feature (prompt prefix caching), the "curated messages" approach should:

1. **Static system prompts**: Cache the system prompt prefix (DeepSeek's context caching automatically reuses tokenized prefixes across calls — no code change needed, just keep system prompts identical across calls for the same task)
2. **Structured message arrays**: Build prompts as a fixed-format message array `[{role: "system", content: SYS_PROMPT}, {role: "user", content: DATA_PROMPT}]` where `SYS_PROMPT` is identical per task type and `DATA_PROMPT` contains the variable data. DeepSeek's API cache hits on the common prefix
3. **Symbol-specific cache busting**: When a symbol gets new agent results, new catalysts, or a material price move, call `llm_cache_invalidate_symbol(symbol)` to force fresh synthesis
4. **Task-type keyed hashing**: `cache_key = hashlib.sha256(f"{task_type}:{symbol}:{data_version_hash}:{model}".encode()).hexdigest()` — different task types get separate cache entries even for the same symbol

### Integration

Wrap `llm_lane.generate()` and `local_llm.generate()` with `cached_generate()` that checks cache before calling. Callers provide a `cache_key` (e.g., `f"{symbol}:{data_freshness_hash}:{task}"`) and optional `cache_ttl_minutes`. Config in `config/inference_layers.yaml:cache:`.

### Config Changes for Caching

| File | Change |
|------|--------|
| **New: `scripts/lib/llm_cache.py`** | Core caching module (SQLite) |
| `config/inference_layers.yaml` | Add `cache:` section (tier TTLs, max entries, DB path, DeepSeek prefix-cache hints) |
| `scripts/llm_lane.py` | Add `cached_generate()` wrapper |
| `scripts/local_llm.py` | Add `cached_generate()` wrapper |
| `scripts/process_watchlist_agent_jobs.py` | Wrap agent calls with cache-aware key; maintain `data_version_hash` per symbol |
| `scripts/catalyst_classifier.py` | Wrap with `(article_id, model)` key |
| `scripts/watchlist_entry_planner.py` | Wrap with `(symbol, price_bucket, rsi_bucket)` key |

---

## Implementation Priority Order (Recommended)

### Phase 1: Registry Completeness (config only, no code risk)
1. Add 13 missing page entries to `config/data_registry.yaml:consumers.pages`
2. Add 21 missing alert entries to `config/data_registry.yaml:consumers.alerts`
3. Add missing endpoint rows to 7 partially-declared page entries
4. Add outbound notification channel entries
5. Run `check_coverage --strict` to verify

### Phase 2: DeepSeek Flash as PRIMARY (with fallback chain)
6. Add `deepseek-flash` lane to `llm_lane.py` as DEFAULT lane (API key from Bitwarden `deepseek_tradeai`)
7. Add API key entry, budget caps (2000/day), process registry entries
8. Route Core Operational agents through Flash in `process_watchlist_agent_jobs.py`:
   - Maria, Steph, Risk Agent, Tax Agent → Flash primary, gemma3:4b fallback
   - Scalp Critic → Flash primary, gemma fallback
   - Aegis (routine classification: social sentiment, transcripts, ingestion) → Flash primary
9. Route L1-L3 curation through Flash in `agent_watchlist_engine.py`
10. Route Hermes Research Fleet (Coordinator + 10 LLM components) through Flash in hermes dispatch
11. Route SHADOW fleet through Flash: modify `scripts/agent_runtime/critic_llm.py` — set `AGENT_RUNTIME_SHADOW_MODEL=deepseek-flash` as default, gemma3:4b as fallback, grok escalation becomes fallback tier
12. Wire fallback chain: DeepSeek Flash → gemma3:4b → grok-3-mini (remove paid Anthropic/OpenAI fallbacks or gate them)
13. Add liveness health check and keepalive ping

### Phase 3: LLM Caching
14. Create `scripts/lib/llm_cache.py`
15. Add `cached_generate()` to `llm_lane.py` and `local_llm.py`
16. Wrap highest-volume call sites:
    - Agent analyses (Maria/Steph/Risk/Tax every 15 min — 40+ calls/hr)
    - Catalyst classification (per-article, 3x daily + continuous RSS)
    - Entry plans (per-symbol, up to 400/weekend)
    - SHADOW fleet critic calls (event-driven, 16 agents × event frequency)
17. Add `data_version_hash` tracking per symbol

### Phase 4: DeepSeek v4 as PRIMARY for CIO (with fallback chain)
18. Add `deepseek-v4` lane for CIO synthesis, arbiter, escalation (same `deepseek_tradeai` key)
19. Route v4 to Core agents: Alex-CIO (primary), Aegis synthesis/brief generation (primary), Iris proposal consensus (replaces claude lane)
20. Route v4 to SHADOW agent: Alex-SHADOW (CIO synthesis critic) — modify `critic_llm.py` to support per-agent model override for v4
21. Set v4 as CIO_DEFAULT in `process_watchlist_agent_jobs.py` — grok+gpt dual-consensus becomes fallback only
22. Wire v4 into dual-consensus arbiter, ensemble 4th lane, escalation handler
23. Remove paid Anthropic/OpenAI fallbacks from `local_llm.py` (gate behind `ALLOW_PAID_FALLBACK=true` env var, default: false)

### Phase 5: Alert Broker Routing + Outbound
24. Route registered alerts through broker wrappers
25. Consolidate 10+ direct Telegram senders through central chokepoint
