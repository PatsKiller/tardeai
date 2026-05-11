# Trade AI v12 -- Master System Documentation

**Owner:** John W. Whiting
**Server:** ms01-openclaw (Linux, Ubuntu)
**Document version:** 2026-05-11 (Session 29 — Phases 1-8 Complete: Classification, Intelligence, Consolidation, LLM, UI/UX, Feedback, Production)
**Status:** Paper trading validation -- 6-month window before live consideration

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Service Architecture](#2-service-architecture)
3. [Runtime Topology](#3-runtime-topology)
4. [Database Layer](#4-database-layer)
5. [Pipeline Architecture](#5-pipeline-architecture)
6. [External Research & Signal Ingestion](#6-external-research--signal-ingestion)
7. [Screener System](#7-screener-system)
8. [Strategy Engine](#8-strategy-engine)
9. [Incubator Pipeline](#9-incubator-pipeline)
10. [Proposal Lifecycle](#10-proposal-lifecycle)
11. [Agent Layer](#11-agent-layer)
12. [LLM Subsystem](#12-llm-subsystem)
13. [API Layer](#13-api-layer)
14. [Frontend](#14-frontend)
15. [Notification & Alerting](#15-notification--alerting)
16. [Scheduling & Orchestration](#16-scheduling--orchestration)
17. [Security & Access Control](#17-security--access-control)
18. [Failure Modes & Recovery](#18-failure-modes--recovery)
19. [Safety Rules (Non-Negotiable)](#19-safety-rules-non-negotiable)
20. [Key File Locations](#20-key-file-locations)
21. [Known Constraints](#21-known-constraints)
22. [Glossary](#22-glossary)

---

## 1. Executive Summary

Trade AI v12 is an automated trading intelligence and portfolio management platform. It operates as a single-tenant, self-hosted service on a dedicated Linux server, combining:

- **Data ingestion** from 15+ external sources (market data, news, SEC filings, transcripts, social, economic indicators)
- **31-stage pipeline** organized into 7 groups running pre-market through overnight
- **23 dynamically loaded strategies** (YAML-driven, multi-assignment capable)
- **LLM-assisted classification** with a 3-provider fallback chain (local GPU-accelerated primary → OpenAI → Anthropic)
- **6 AI agents** accessible via Telegram/WhatsApp (Maria, Steph, Alex, Aegis, Risk Agent, Tax Agent)
- **Iris backend agent** for content hygiene + Scalp Critic for incubator gating
- **Paper trading execution** via Alpaca with bracket orders, TCA, and reconciliation
- **42-page React dashboard** (Command Center v2, consolidated from 61) for operator control
- **Feedback loop closure** with proposal outcome chains, alert effectiveness scoring, and agent calibration
- **LLM intelligence enrichment** generating daily narratives across 5 surfaces via qwen3:14b

The platform manages a ~$1.19M portfolio (taxable + IRA, ~50 positions) in **paper-only mode**. Live trading is locked behind a 6-month validation gate requiring 55% win rate and 1.3 profit factor.

### System Scale

| Metric | Value |
|--------|-------|
| Python scripts | 364 |
| Cron jobs | 53 (flock-protected, weekday/weekend/monthly schedules) |
| API endpoints | 275+ (api_v2.py + portfolio_server.py) |
| Database tables | 330 |
| SQL migrations | 37 |
| Strategies | 23 (YAML-driven, multi-assignment) |
| Frontend pages | 42 primary routes (consolidated from 61 via TabPage) |
| Nav items | 42 across 8 groups |
| Agents | 6 conversational (Maria, Steph, Alex, Aegis, Risk, Tax) + 2 backend (Iris, Scalp Critic) |
| External data sources | 15+ |
| Research topics | 17 (DB-driven, LLM-curated) |
| News articles ingested | 3,022+ |
| Social posts ingested | 2,248+ |
| Incubator symbols | 1,139 active |
| Telegram alert scripts | 56 (routed through central alert_dispatcher) |
| LLM intelligence sections | 5 (generated daily via qwen3:14b) |

---

## 2. Service Architecture

Trade AI v12 has 6 distinct service boundaries:

### Service Boundary Map

```
+-------------------------------------------------------------------+
|                          ms01-openclaw                              |
|                                                                    |
|  +------------------+    +------------------+    +---------------+ |
|  | Portfolio Server  |    | Ollama LLM       |    | OpenClaw GW   | |
|  | :7777 (HTTP+Auth) |<-->| :11434           |<-->| :18789        | |
|  | 275+ API endpoints|    | qwen3:14b        |    | 6 agents      | |
|  | React SPA @ /v2/  |    | Intel Arc B50    |    | Telegram/WA   | |
|  +--------+----------+    +------------------+    +---------------+ |
|           |                                                        |
|  +--------v---------+    +------------------+    +---------------+ |
|  | PostgreSQL 15     |    | Cron Scheduler   |    | Alert Dispatch| |
|  | :5432             |    | 53 jobs          |    | Dedup+Fatigue | |
|  | 330 tables        |    | flock-protected  |    | 3 tiers       | |
|  +-------------------+    +------------------+    +---------------+ |
+-------------------------------------------------------------------+
                    |                    |
     +--------------+--------------------+--------------+
     |              |              |              |      |
+----v----+  +------v-----+  +----v----+  +------v---+  |
| Finviz  |  | News APIs  |  | Broker  |  | Cloud LLM|  |
| Elite   |  | 7 sources  |  | Alpaca  |  | xAI/Anth/|  |
|         |  |            |  | (paper) |  | OpenAI   |  |
+---------+  +------------+  +---------+  +----------+  |
                                                         |
                              +----v----+  +------v---+  |
                              | SEC/FRED|  | YouTube  |  |
                              | Gov Data|  | Transcr. |  |
                              +---------+  +----------+  |
```

### Cloud-Equivalent Mapping

| Current (Self-Hosted) | AWS Equivalent | Azure Equivalent |
|----------------------|----------------|------------------|
| Portfolio Server (Flask :7777) | ECS Fargate + ALB | Azure Container Apps + App Gateway |
| PostgreSQL 15 (:5432) | RDS PostgreSQL | Azure Database for PostgreSQL |
| Ollama LLM (:11434) | EC2 g5 instance / Bedrock | Azure ML GPU VM / Azure OpenAI |
| OpenClaw Gateway (:18789) | ECS Fargate | Azure Container Apps |
| Cron Scheduler | EventBridge Scheduler | Azure Logic Apps / Timer Triggers |
| React SPA | S3 + CloudFront | Azure Blob + CDN |
| Scalp WebSocket | API Gateway WebSocket | Azure Web PubSub |

### Deployment Model

**Current:** Single-tenant, single-server deployment. All services co-located on `ms01-openclaw`.

**Cloud target:** Single-tenant, multi-service deployment:
- Compute services containerized (Docker)
- Database as managed service
- LLM inference as GPU-accelerated container or managed API
- Static frontend served from object storage + CDN
- Cron replaced by managed scheduler

---

## 3. Runtime Topology

| Service | Port | Process | Health Check |
|---------|------|---------|-------------|
| Portfolio Server | 7777 | `scripts/portfolio_server.py` | `GET /api/v2/system-health` |
| PostgreSQL 15 | 5432 | `postgresql` | `pg_isready` |
| Ollama LLM | 11434 | `ollama serve` | `GET /api/tags` |
| OpenClaw Gateway | 18789 | OpenClaw daemon | `GET /health` |
| Scalp WebSocket | 7778/7779 | Scalp feed server | TCP connect |
| Frontend (Vite) | via 7777 | Served as static from Portfolio Server | `GET /v2/` |

**Project root:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`

### Systemd Services

| Unit | Type | Purpose |
|------|------|---------|
| `tradeai-continuous.service` | user | Portfolio server + continuous runner |
| `tradeai-continuous.timer` | user | Auto-restart timer |
| `aegis-overnight.service` | user | Aegis synthesis jobs |
| `aegis-surveillance.service` | user | Aegis overnight monitoring |
| `portfolio-daily.service` | user | Daily portfolio operations |
| `recovery-watch.service` | user | Stop-out detection loop |
| `ollama.service` (override) | system | GPU-accelerated LLM server |

---

## 4. Database Layer

- **Engine:** PostgreSQL 15
- **Table count:** 330
- **Connection:** `localhost:5432`, database `trade_ai`, user `trade_ai`
- **Backup:** 7-day rolling `pg_dump` to `backups/db/trade_ai_*.sql.gz`

### Schema Groups

| Group | Key Tables | Purpose |
|-------|-----------|---------|
| **Trading Core** | `trade_ai_scans`, `paper_trade_proposals`, `paper_trades` | Screener results, proposals, executed trades |
| **Incubator** | `incubator_universe`, `ticker_strategy_classifications` | Symbol lifecycle, strategy assignments |
| **Intelligence** | `watchlist_agent_results`, `intelligence_entities`, `news_articles` | Agent outputs, NLP entities, news corpus |
| **Market Data** | `market_quotes`, `indicator_confluence_cache`, `fundamental_data` | Prices, technicals, fundamentals |
| **Enrichment** | `ticker_enrichment_cache`, `catalyst_cache` | 60+ Finviz fields, catalyst data |
| **Strategy** | `strategy_signals`, `strategy_configs` | Signal history, dynamic config |
| **Execution Quality** | `paper_execution_quality`, `broker_reconciliation_items`, `trade_thesis_outcomes` | TCA metrics, recon, outcome tracking |
| **Agent** | `cio_decisions`, `decision_outcomes`, `agent_handoffs` | Decision audit trail (CIO deduped per 24h) |
| **Recovery** | `stopped_out_watch`, `stopped_out_relist_events`, `stopped_out_watch_history` | Exit classification (true stop-out vs relist vs market reconnection), patience scoring |
| **Portfolio** | `portfolio_holdings`, `portfolio_accounts`, `personal_situation` | Positions, accounts, personal data |
| **System** | `pipeline_runs`, `daily_system_metrics` | Pipeline health, trending |
| **Feedback Loops** | `proposal_outcome_chain`, `alert_effectiveness`, `strategy_performance_snapshots`, `agent_sample_tracking`, `recovery_outcome_log`, `cio_decision_responses` | Closed-loop tracking: proposal → trade → P&L → agent calibration |
| **LLM Cache** | `llm_intelligence_cache` | 5 daily-generated LLM narratives (portfolio risk, rebalance, recovery, morning, prospects) |
| **Research** | `sec_form4`, `youtube_transcripts` | Filings, transcript archive |
| **Topic Intelligence** | `topic_monitor`, `content_entity_links`, `blocked_content`, `iris_library_gap_fills`, `topic_curation_feedback` | Topic research, entity linking, quality gating, learning loop |

### Critical Data Volumes

| Table | Approximate Rows | Growth Rate |
|-------|------------------|-------------|
| `news_articles` | 3,022+ | +200/week |
| `social_posts` | 2,248+ | +150/week |
| `incubator_universe` | 1,139 active | +50/week (rolloff cleans stale) |
| `trade_ai_scans` | 640 (current window) | 40-120/day weekdays |
| `cio_decisions` | 446 (deduped per 24h) | +15/day unique |
| `notification_log` | 90 | +5-10/day |
| `proposal_outcome_chain` | 38 | Grows with proposals |
| `alert_effectiveness` | 31 | +5-10/week |
| `llm_intelligence_cache` | 5 | Refreshed daily |

---

## 5. Pipeline Architecture

The pipeline runs **31 stages organized into 7 groups**. Each group has a designated time window and dependency chain.

```
[1. DATA COLLECTION] >>> [2. ENRICHMENT] >>> [3. SCORING] >>> [4. INTELLIGENCE] >>> [5. PROPOSALS] >>> [6. EXECUTION] >>> [7. OVERNIGHT]
    6-7 AM                   7-8 AM            8-9 AM           continuous          throughout day      market hours         8 PM+
```

### Group 1 -- Data Collection (6-7 AM M-F)

| Stage | Script | Inputs | Outputs |
|-------|--------|--------|---------|
| Finviz Screener Runner | `finviz_screener_runner.py` | Finviz Elite API (cookie + token) | `trade_ai_scans` rows |
| Social Ingest | `social_ingest.py` | Social media feeds | Sentiment scores |
| News Ingestion | `news_ingestion.py` | NewsAPI, Finnhub, FMP, Polygon, RSS | `news_articles` rows |
| FRED Data Ingest | `fred_data_ingest.py` | Federal Reserve API | Economic indicators |
| SEC Data Ingest | `sec_data_ingest.py` | SEC EDGAR | `sec_form4` (insider filings) |

### Group 2 -- Enrichment (7-8 AM M-F)

| Stage | Script | Inputs | Outputs |
|-------|--------|--------|---------|
| Finviz Enrichment | `finviz_enrichment.py` | Finviz 5-view pages | 60+ fields per symbol in `ticker_enrichment_cache` |
| Catalyst Enrichment | `catalyst_enrichment.py` | 7 API sources | `catalyst_verified` flag, `catalyst_cache` |
| Symbol Enrichment | `symbol_enrichment.py` | Fundamental APIs | `fundamental_data` |
| RAG Indexer | `rag_indexer.py` | News + transcripts + filings | Vector embeddings for search |

### Group 3 -- Scoring (8-9 AM M-F)

| Stage | Script | Inputs | Outputs |
|-------|--------|--------|---------|
| Trade AI Orchestrator | `trade_ai_orchestrator.py` | Scans + enrichment | 55-point scores, GO/WAIT/NO-GO |
| Indicator Engine | `indicator_engine.py` | yfinance OHLCV | 17 technical indicators in `indicator_confluence_cache` |
| Premarket Watcher | `premarket_watcher.py` | Pre-market quotes | Gap and volume alerts |
| Agent Router | `agent_router.py` | Scored symbols | Routes to appropriate agent |

### Group 3b -- Sentiment & Signal Fusion (7 AM, 12 PM M-F)

| Stage | Script | Inputs | Outputs |
|-------|--------|--------|---------|
| Sentiment Processor | `sentiment_processor.py` | Unscored news_articles | sentiment + sentiment_score on each article; sentiment_observations |
| Signal Fusion | `signal_fusion.py` | catalyst + news + social + sentiment | `fused_signals` (strategy-weighted composite per symbol) |
| Topic Curator | `topic_curator.py --improve-queries` | Recent articles + LLM | Content ratings, entity links, improved search queries → auto-ingestion |

### Group 4 -- Intelligence (Continuous)

| Stage | Script | Inputs | Outputs |
|-------|--------|--------|---------|
| Watchlist Agent Jobs | `process_watchlist_agent_jobs.py` | Job queue + RAG + sentiment + social + fused + peers | Agent analysis results |
| Agent Event Router | `agent_event_router.py` | agent_event_queue | Routes events → agent jobs; handles CONTENT_GAP and RESEARCH_MORE |
| Agent Watchlist Engine | `agent_watchlist_engine.py` | Agent outputs | Updated watchlists |
| CIO Decision Engine | `cio_decision_engine.py` | All intelligence | `cio_decisions` |
| Pipeline Watchdog | `pipeline_watchdog.py` | `pipeline_runs` | Failure alerts + auto-retry |

### Group 5 -- Proposal Pipeline

| Stage | Script | Inputs | Outputs |
|-------|--------|--------|---------|
| Weekly Incubator Builder | `weekly_incubator_builder.py` | Qualified scans | `incubator_universe` rows |
| Daily Incubator Refresh | `daily_incubator_refresh.py` | Incubator symbols | Updated scores/catalysts |
| Incubator Rolloff | `incubator_rolloff_engine.py` | Decayed symbols | Removed entries |
| Proposal Promoter | `incubator_proposal_promoter.py` | ACTIVE incubator | `paper_trade_proposals` |
| Proposal Enrichment | `proposal_enrichment_loop.py` | Open proposals | Enriched data packets |
| Proposal Lifecycle | `proposal_lifecycle.py` | Proposal states | State transitions |

### Group 6 -- Execution (Automated, Market Hours)

| Stage | Script | Trigger | Outputs |
|-------|--------|---------|---------|
| Risk Gate | `risk_gate.py` | On proposal creation | Pass/fail + reason codes. Paper cap $15K (env: `PAPER_MAX_POSITION_SIZE`) |
| Instant Submission | `api_v2.py` → `proposal_paper_submitter.py` | On approval click | Immediate Alpaca order (market or limit based on price proximity) |
| Smart Order Type | `alpaca_paper_adapter.py` | During submission | Market if price ≤ entry or within 2%; limit+bracket if >2% above |
| Execution Sweep | `paper_execution_sweep.py` | Every 5 min (cron safety net) | Catches approved proposals not yet submitted |
| Position Monitor | `paper_trade_monitor.py` | Every 5 min (cron) | R-multiple trailing stops, target detection, automatic closes |
| Broker Reconciliation | `alpaca_paper_reconciler.py` | On fill events | `broker_reconciliation_items` |
| Execution Quality | `execution_quality_analyzer.py` | On trade close | TCA metrics |

### Group 7 -- Overnight (8 PM - 6 AM)

| Stage | Script | Inputs | Outputs |
|-------|--------|--------|---------|
| Overnight Batch | `overnight_batch.py` | Daily data | Consolidated metrics |
| Agent Outcome Scorer | `agent_outcome_scorer.py` | Past recommendations | Performance grades |
| Strategy Weekly Review | `strategy_weekly_review.py` | Strategy signals | Performance reports |
| Overnight Embeddings | `overnight_batch_embeddings.py` | New content | Refreshed RAG index |

---

## 5b. Closed-Loop Intelligence Pipeline (Session 37)

The system operates as a **closed-loop intelligence engine**, not a data warehouse. Every data source feeds into correlation, every agent analysis feeds back into new searches, and every failure triggers a notification.

### Full-Circle Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CLOSED-LOOP INTELLIGENCE                         │
│                                                                     │
│   INGEST ──→ CORRELATE ──→ SENTIMENT ──→ CURATE ──→ AGENTS        │
│     ↑          by symbol     score all      LLM rate     analyze   │
│     │          + entity      + fuse          + link       + judge   │
│     │                                                      │        │
│     │          ┌──────────────────────────────────────────┘        │
│     │          ▼                                                    │
│     │     DEMAND SIGNAL                                             │
│     │     ├─ CONTENT_GAP (Iris detects missing coverage)           │
│     │     ├─ RESEARCH_MORE (agents need more data)                 │
│     │     └─ IMPROVED QUERIES (curator learns what's missing)      │
│     │          │                                                    │
│     └──────────┘  auto-trigger: search → ingest → score →          │
│                   RAG re-index → re-analyze → Telegram notify      │
└─────────────────────────────────────────────────────────────────────┘
```

### Layer Detail

| Layer | Script(s) | Input | Output | Cadence |
|-------|-----------|-------|--------|---------|
| **Ingest** | news_ingestion, social_ingest, youtube_transcript_ingest, sec_data_ingest | External APIs | Raw rows in news_articles, social_posts, youtube_transcripts | 2-3x daily + on-demand |
| **Correlate** | intelligence_entity_manager, topic_curator (extract_and_link_entities) | Raw content | content_entity_links (symbol ↔ content), intelligence_entities (per-symbol score) | After each ingest |
| **Sentiment** | sentiment_processor, signal_fusion | news_articles, social_posts | sentiment_observations (per-article), fused_signals (per-symbol composite) | 2x daily (7 AM, 12 PM) |
| **Curate** | topic_curator (rate_pending_content, improve_queries) | Pending content + LLM | rag_status=approved/blocked, llm_generated_queries, content_entity_links | Daily 7 AM |
| **Agent Analysis** | process_watchlist_agent_jobs | RAG + sentiment + social + fused + peers + playbook | watchlist_agent_results (recommendation, confidence, narrative) | Every 15 min |
| **Demand Signal** | agent_event_router (handle_content_gap, handle_research_more_demand) | CONTENT_GAP events, RESEARCH_MORE recommendations | Auto-triggered: topic_ingestion → sentiment → RAG → re-analysis | On event |
| **Feedback** | agent_outcome_scorer, learning_governance | Closed trades vs prior recommendations | agent_calibration (win rate, PnL), confidence adjustments | Daily 5:30 AM |
| **RAG Index** | rag_indexer | All approved content + agent results + synthesis | Vector embeddings for semantic search | 4x daily + on gap-fill |

### Agent Context Injection (per symbol analysis)

Every time an agent analyzes a symbol, it receives this full context stack:

```
1. Scan Intelligence    — screener position, score, decision (GO/WAIT/AVOID)
2. RAG Pre-Context      — top 5 prior intelligence items (news, transcripts, agent results)
3. News Sentiment (7d)  — article count, avg score, headlines with sentiment labels
4. Social Sentiment (7d)— post count, bullish/bearish/neutral breakdown, top posts
5. Fused Signal         — strategy-weighted composite (catalyst + news + social + sentiment)
6. Peer Agent Notes     — what other agents concluded on this symbol recently
7. Content Gap Warnings — Iris librarian flags on missing coverage
8. Technical Confluence — RSI, SMA, ATR, confluence tier
9. Prospects Context    — pipeline position (incubator, proposal, paper trade)
10. Calibration Data    — agent's own win rate, avg confidence, past PnL on similar
11. Strategy Playbook   — role instructions, entry/exit rules, risk parameters
12. Global Rules G1-G10 — income protection, SSDI awareness, confidence gating
```

### Demand-Driven Search Loop

When agents need more data, the system auto-responds:

| Trigger | Source | Action Chain |
|---------|--------|-------------|
| **CONTENT_GAP** | Iris librarian detects missing coverage | topic_ingestion → news search → sentiment_processor → RAG re-index → Maria re-queued |
| **RESEARCH_MORE** | Agent outputs low-confidence RESEARCH_MORE | Checks watchdog_actions for recent fills → fires synthetic CONTENT_GAP → full search loop |
| **Improved Queries** | topic_curator generates better search terms | Auto-runs topic_ingestion --use-llm-queries → new content flows back to curation |

### Per-Agent Full-Circle Integration

| Agent | Reads | Writes | Triggers | LLM Model |
|-------|-------|--------|----------|-----------|
| **Maria** | RAG, sentiment, social, fused, peers, playbook, scans | watchlist_agent_results (BUY/HOLD/AVOID + narrative) | Re-analysis on gap-fill; debate on SEC insider buy | qwen3:14b (2-pass: sentiment + fundamentals) |
| **Steph** | Portfolio state, allocation targets, income projections, sentiment | watchlist_agent_results (ADD/TRIM/HOLD + allocation review) | Escalation queue for concentration risk; INCOME_CRITICAL flag | qwen3:14b |
| **Alex** | Roth conversion models, IRMAA thresholds, tax brackets, retirement RAG | Research reports, Roth ladder plans, monthly reviews | Auto-queued on SEC insider buy consensus; weekly/monthly research | qwen3:14b + Claude (complex) |
| **Aegis** | All agent results, portfolio positions, overnight events | Morning briefs, synthesis reports, cross-agent coordination | Morning brief delivery; post-trade synthesis writeback | qwen3:14b |
| **Iris** | Content freshness, RAG coverage, duplicate detection, entity staleness | Hygiene proposals, CONTENT_GAP events, taxonomy proposals | CONTENT_GAP → auto-search; hygiene escalations to John | qwen3:14b (classification) |
| **Scalp Critic** | Incubator candidates, catalyst data, technicals, news/social | llm_screen_grade (A-F), verdict (PROMOTE/HOLD/DROP) | Gates incubator → proposal promotion | qwen3:14b |

### Agent LLM Flow

```
Symbol enters pipeline
    ↓
qwen3:14b Pass 1 (sentiment + catalyst analysis)
    ↓
qwen3:14b Pass 2 (fundamental + technical synthesis)
    ↓
Combined result → JSON (recommendation, confidence, narrative)
    ↓
Stored in watchlist_agent_results
    ↓
Indexed into RAG (8h cadence)
    ↓
Available to next agent analyzing same symbol
    ↓
Outcome scorer matches to closed trades → calibration update
    ↓
Next run: agent sees updated calibration → adjusts confidence
```

### Daily Intelligence Workflow (End-to-End)

This is the complete day-in-the-life showing how data flows from raw ingestion through agent analysis, LLM curation, and back into smarter searches:

```
5:00 AM ─ Alex daily retirement scan
5:30 AM ─ Agent outcome scorer (grade yesterday's recommendations)
6:00 AM ─ Credential monitor + previously traded watchlist
6:30 AM ─ NEWS INGESTION (Yahoo RSS, Finnhub, Seeking Alpha, Google News)
          └→ ~40-60 articles ingested → auto-approved for RAG
6:30 AM ─ SOCIAL INGESTION (StockTwits, Reddit)
          └→ ~100-200 posts with sentiment scored at ingest
6:45 AM ─ Topic ingestion (gap-fill mode: only topics with <3 articles)
6:50 AM ─ RAG indexer (embed new news, transcripts, social posts)
7:00 AM ─ SENTIMENT PROCESSOR (score all unscored articles)
          └→ Lexicon analysis: positive/negative/neutral + confidence
7:00 AM ─ TOPIC CURATOR (the learning engine):
          ├─ [1] Rate pending content (LLM decides: approved/low_quality/blocked)
          ├─ [2] Extract entities (LLM finds tickers/topics → content_entity_links)
          ├─ [3] Improve queries (LLM reviews what was found → generates better queries)
          ├─ [3b] AUTO-INGEST with improved queries (runs topic_ingestion --use-llm-queries)
          ├─ [4] RAG re-index (embed newly approved content)
          └─ [5] Fire agent events (TOPIC_INTELLIGENCE → notify relevant agents)
7:15 AM ─ SIGNAL FUSION (fuse catalyst + news + social + sentiment per symbol)
          └→ Strategy-weighted composite: e.g. defense_thesis weights catalyst 0.45
8:10 AM ─ Incubator LLM screener (grade top candidates A-F, PROMOTE/HOLD/DROP)
8:15 AM ─ Daily incubator refresh (update scores, RVOL, catalyst freshness)
8:20 AM ─ INCUBATOR PROPOSAL PROMOTER (promote grade A/B candidates to proposals)

─── MARKET HOURS (9 AM - 4 PM) ───

Every 15 min:
  ├─ Event detector → agent_event_queue (STOP_TRIGGERED, RSI_EXTREME, etc.)
  ├─ Agent event router:
  │   ├─ CONTENT_GAP → auto-search + ingest + sentiment + RAG + re-analyze
  │   ├─ RESEARCH_MORE → demand-driven search loop
  │   └─ Other events → route to appropriate agents
  └─ Process agent jobs (Maria, Steph, Risk analyze symbols with 12-layer context)

12:00 PM ─ Sentiment processor (midday refresh)
12:15 PM ─ Signal fusion (midday refresh)
12:30 PM ─ News ingestion (midday)
12:35 PM ─ Social ingestion (midday)

─── EVENING (6-10 PM) ───

6:00 PM ─ Incubator LLM screener (evening batch)
6:00 PM ─ Incubator rolloff (remove stale candidates)
6:10 PM ─ Proposal promoter (evening promotion)
7:00 PM ─ YouTube transcript ingest (all 48 tracked channels)
8:00 PM ─ Overnight batch + SEC data ingest

─── OVERNIGHT ───

Agent jobs continue processing (25 per 5 min)
RAG re-indexer (agent results + synthesis, 8h cadence)
Agent outcome scorer and learning governance update calibration
```

### LLM Curation Schedule (When Does It Get Smarter?)

| When | What Happens | LLM Used |
|------|-------------|----------|
| **7:00 AM daily** | topic_curator rates pending content (approved/low_quality/blocked) | qwen3:14b (~15s per article) |
| **7:00 AM daily** | topic_curator extracts tickers + topics → content_entity_links | qwen3:14b |
| **7:00 AM daily** | topic_curator improves queries: reviews last week's articles, generates 4 targeted news + 4 video queries per topic, tailored to John's situation | qwen3:14b |
| **7:00 AM daily** | Auto-ingests with improved queries (step 3b → topic_ingestion --use-llm-queries) | N/A (search APIs) |
| **8:10 AM + 6 PM** | Incubator LLM screener grades candidates (catalyst assessment, momentum, confidence) | qwen3:14b |
| **On CONTENT_GAP** | Agent event router auto-triggers: topic search → news search → sentiment score → RAG re-index → re-queue analysis | qwen3:14b (agent re-analysis) |
| **On RESEARCH_MORE** | Multiple agents say "need more data" → synthetic CONTENT_GAP → full search loop | qwen3:14b |
| **5:30 AM daily** | Outcome scorer grades past recommendations (CORRECT/PARTIAL/WRONG) → calibration update | N/A (rule-based) |
| **Sunday 6 AM** | Iris hygiene: demote stale content, detect superseded regulatory data | N/A (rule-based) |
| **Sunday 7 PM** | Weekly incubator rebuild with LLM multi-strategy classification | qwen3:14b |

### Query Improvement Example (How the System Learns)

The LLM reviews what was found last run and generates increasingly targeted queries:

**Static queries (original):**
```
"SSDI benefits update 2026"
"social security disability income limits"
```

**LLM-improved queries (after learning John's situation):**
```
"Roth conversion strategies for SSDI beneficiaries with $40K income and MFS filing in New York"
"2026 IRMAA income thresholds for SSDI recipients and Roth conversion planning"
"How MFS filing affects IRMAA lookback for Medicare beneficiaries starting in 2026"
"Safe Dividend Stocks for SSDI Recipients: 4-8% Yield Without IRMAA Risk"
```

The curator stores these in `topic_monitor.llm_generated_queries` and auto-runs ingestion with them. Each daily cycle produces more targeted results.

---

## 6. External Research & Signal Ingestion

### Active Data Sources

| Source | API / Method | Data Type | Query Frequency | Fallback |
|--------|-------------|-----------|----------------|----------|
| **Finviz Elite** | HTTP scrape (cookie + API token) | Screener results, 60+ enrichment fields | 4x daily (04:00, 07:00, 09:00, 10:00) | None -- primary screener, manual cookie refresh required |
| **NewsAPI** | REST API (key) | News articles, headlines | 2x daily (06:30, 12:30) + on-demand | Finnhub news fallback |
| **Finnhub** | REST API (key) | News, company filings, insider activity | On enrichment trigger | NewsAPI fallback |
| **Polygon** | REST API (key) | Market data, quotes, corporate events | On catalyst enrichment | Yahoo Finance |
| **FMP (Financial Modeling Prep)** | REST API (key) | Fundamentals, earnings, financial statements | On catalyst enrichment | AlphaVantage |
| **AlphaVantage** | REST API (key) | Fundamentals, economic indicators | On enrichment | FMP fallback |
| **Yahoo Finance (yfinance)** | Python library | OHLCV, quotes, dividends | Indicator refresh (5:45 AM), on-demand | Polygon |
| **FRED** | REST API (key) | Federal Reserve economic data (rates, CPI, employment) | Daily (6 AM) | Cached last-known values |
| **SEC EDGAR** | REST API (public) | Form 4 insider filings | Daily (8 PM) | Skip -- non-critical |
| **YouTube Transcripts** | `youtube-transcript-api` | Video transcripts for financial analysis | Monthly discovery + daily channel scan | Skip -- supplementary |
| **Alpaca** | REST API (key) | Paper trade execution, fills, positions | On execution + reconciliation | Manual fallback |
| **Ollama (local LLM)** | HTTP (:11434) | Classification, review, health checks | Continuous (toll-gated) | Cloud LLM cascade |
| **Brave Search** | REST API (key) | News search for topic ingestion | On topic ingestion | DuckDuckGo fallback |
| **Google News RSS** | RSS feed | Topic-targeted news articles | On topic ingestion | Brave Search |
| **DuckDuckGo** | HTML scrape | News search fallback | On topic ingestion | None |
| **StockTwits** | REST API | Social sentiment, post volume | 2x daily (6:30 AM, 12:35 PM) | Reddit only |
| **Reddit** | REST API | Social discussion, sentiment | 2x daily (6:30 AM, 12:35 PM) | StockTwits only |
| **2Captcha** | REST API (key) | CAPTCHA solving for protected sites | On-demand when blocked | Skip site |

### 2Captcha Integration

**API Key:** `.env` → `TWOCAPTCHA_API_KEY`

2Captcha enables automated data collection from sites that block scrapers with CAPTCHAs. The system can solve:

| CAPTCHA Type | Supported Sites | Use Case |
|-------------|-----------------|----------|
| **reCAPTCHA v2/v3** | Seeking Alpha, TipRanks, Glassdoor, SEC EDGAR (rate-limited) | Article scraping, analyst ratings, insider filing deep-dive |
| **hCaptcha** | Finviz (when rate-limited), Discord (social scraping) | Screener data when cookies expire, social sentiment from Discord |
| **Cloudflare Turnstile** | Many financial news sites, MarketWatch, Barron's | Premium article access, paywall-adjacent content |
| **Image CAPTCHA** | Legacy financial sites, government portals | SSA.gov data, state regulatory filings |
| **FunCaptcha** | LinkedIn (company data) | Executive changes, hiring signals |
| **GeeTest** | Some Asian market data providers | International ETF/ADR data |

**Integration pattern** (for any ingestion script):
```python
import os, requests

def solve_captcha(site_url, site_key, captcha_type="recaptcha_v2"):
    api_key = os.getenv("TWOCAPTCHA_API_KEY")
    if not api_key:
        return None  # skip — no captcha solving available

    # Submit captcha task
    resp = requests.post("https://2captcha.com/in.php", data={
        "key": api_key, "method": "userrecaptcha",
        "googlekey": site_key, "pageurl": site_url,
        "json": 1
    }).json()

    task_id = resp.get("request")
    # Poll for solution (typically 10-30 seconds)
    for _ in range(30):
        time.sleep(5)
        result = requests.get(f"https://2captcha.com/res.php?key={api_key}&action=get&id={task_id}&json=1").json()
        if result.get("status") == 1:
            return result["request"]  # solved captcha token
    return None
```

**Target sites for enhanced ingestion:**

| Site | Data Value | CAPTCHA Type | Priority |
|------|-----------|-------------|----------|
| **Seeking Alpha** | Premium analyst reports, earnings call transcripts | reCAPTCHA v2 | High -- fills content gaps in Alex agent research |
| **TipRanks** | Analyst consensus, price targets, smart score | reCAPTCHA v2 | High -- enriches proposal quality scoring |
| **Finviz** (rate-limited) | Screener when cookie expires | hCaptcha | Medium -- backup for primary screener |
| **MarketWatch** | Premium articles, options flow | Cloudflare | Medium -- broadens news sentiment coverage |
| **Barron's** | Premium analysis, portfolio strategy | Cloudflare | Low -- supplementary for Alex agent |
| **SEC EDGAR** (heavy load) | Bulk insider filing analysis | reCAPTCHA | Low -- only when bulk-downloading |

**Cost:** ~$2-3 per 1,000 CAPTCHAs solved. At current ingestion volume, estimated $5-10/month.

### Why Each Source Is Used

| Source | Signal Provided | Impact if Unavailable |
|--------|----------------|----------------------|
| Finviz Elite | Volume/gap/float screener hits -- **the primary candidate discovery mechanism** | No new candidates surface. Pipeline stalls at Group 1. |
| News APIs (4 sources) | Market-moving events, catalyst verification, sentiment | Catalyst scoring degrades; proposals lack event context |
| Fundamentals (FMP/AV) | Earnings, revenue, debt ratios | Strategy filters using fundamental data produce false negatives |
| Yahoo Finance | OHLCV for 17 technical indicators | Indicator engine outputs stale; confluence scores unreliable |
| FRED | Macro context (rates, unemployment, CPI) | Macro overlay strategies (sector rotation, bond income) lose context |
| SEC EDGAR | Insider buying/selling signals | Insider signal absent; non-blocking for most strategies |
| YouTube Transcripts | Earnings call language, forward guidance | Alex agent income analysis loses qualitative depth |
| Social (StockTwits + Reddit) | Retail sentiment, volume spikes, emerging narratives | Social fusion signal degrades; momentum strategies lose edge |
| Alpaca | Order routing, fill confirmation | Execution halted; proposals queue without fills |
| Local LLM | Classification, critique, health checks | Falls back to cloud LLM (higher cost, higher latency) |
| 2Captcha | Access to CAPTCHA-protected financial sites | Skip protected sites; reduced coverage for premium content |

### Source Availability Handling

```
if source.available:
    ingest(source.data)
    update_freshness(source, now())
elif source.captcha_blocked and TWOCAPTCHA_API_KEY:
    token = solve_captcha(source.url, source.site_key)
    ingest(source.data, captcha_token=token)
elif source.has_fallback:
    ingest(source.fallback.data)
    log_degraded(source)
    alert_operator(source, "degraded")
else:
    use_cached_last_known(source)
    if staleness > source.max_stale_hours:
        alert_operator(source, "stale")
        mark_dependent_stages("degraded")
```

Every source has a `max_stale_hours` threshold. When exceeded, the `pipeline_watchdog` fires a Telegram alert and marks dependent pipeline stages as degraded.

### Research Architecture (Stub -- Not Yet Implemented)

The following integrations are **architecturally designed but not yet live**:

| Integration | Purpose | Status |
|-------------|---------|--------|
| Google Programmable Search API | Broad web research for novel signals | Stub -- endpoint defined, no API key provisioned |
| Earnings transcript provider (e.g., Seeking Alpha, Motley Fool) | Structured earnings call analysis | Stub -- YouTube transcripts used as partial substitute |
| Alternative data feeds (satellite, credit card, app usage) | Non-traditional alpha signals | Planned -- not architectured yet |
| Real-time news streaming (WebSocket) | Sub-second news reaction | Planned -- current batch polling at 2x/day |

When these stubs are activated, they will integrate at the **Group 1 (Data Collection)** and **Group 2 (Enrichment)** pipeline stages.

---

## 6b. Topic Intelligence System (Closed-Loop)

The topic intelligence system discovers, ingests, curates, and links non-symbol research content (SSDI, trusts, sector analysis, etc.) using a closed-loop architecture where each iteration improves the next.

### Architecture

```
[1] INGESTION (topic_ingestion.py)
    17 topics from DB → LLM generates targeted queries →
    YouTube API → Google News RSS → Brave → DuckDuckGo →
    Saved Google search URLs reused → ALL results downloaded
         |
         v
[2] CURATION (topic_curator.py) ← runs automatically after ingestion
    LLM rates: approved / low_quality / blocked →
    LLM extracts entities (tickers, topics, sectors) →
    content_entity_links table connects to existing DB records →
    LLM generates improved queries for next run →
    Triggers RAG re-index of approved content
         |
         v
[3] RAG INDEX (rag_indexer.py)
    Approved content → embeddings → agents consume via RAG
         |
         v
[4] AGENT CONSUMPTION (rag_retrieval.py)
    Agent asks about NVDA → gets topic_intel from entity links →
    Alex gets SSDI articles, Maria gets AI datacenter research
         |
         v
[5] FEEDBACK LOOP (topic_curation_feedback)
    Tickers extracted → Queries that worked → Better queries next run
```

### DB Tables

| Table | Purpose |
|-------|---------|
| `topic_monitor` | 17 topics with queries, saved URLs, personal context, LLM-generated queries |
| `content_entity_links` | Links articles/transcripts to tickers, topics, sectors |
| `blocked_content` | Items never re-downloaded (LLM or operator blocked) |
| `iris_library_gap_fills` | Search attempt log (source, query, results, saves) |
| `topic_curation_feedback` | Learning loop: improved queries, quality notes, tickers found |

### Active Topics (17)

| Priority | Topic | Agent | Content Type |
|----------|-------|-------|-------------|
| P1 | Disability Retirement | Alex | SSDI, benefits, planning |
| P1 | SSDI Benefits | Alex | Benefits updates, limits, rules |
| P1 | SSDI Cash & Asset Shielding | Alex | Asset protection, trusts, ABLE accounts |
| P2 | AI Data Center Build-Out | Maria | Infrastructure, power, cooling, GPUs |
| P2 | IRMAA Medicare Surcharge | Alex | Medicare premiums, income thresholds |
| P2 | Roth Conversion Strategy | Alex | Tax brackets, conversion planning |
| P2 | Top Yield & Dividend Stocks | Steph | High yield, BDCs, CEFs, monthly income |
| P2 | Trust & Estate Planning | Alex | Special needs trusts, ABLE, Medicaid |
| P3 | AI Chip & Materials Layer | Maria | Semiconductors, HBM, packaging |
| P3 | AI Networking Layer | Maria | InfiniBand, optical, switches |
| P3 | Covered Call Income | Steph | CC strategies, ETFs, premium income |
| P3 | Defense Sector Thesis | Maria | Defense budget, AI military |
| P3 | Dividend Income Strategy | Steph | Dividend growth, aristocrats |
| P3 | Emerging Sectors by Sentiment | Aegis | Sector rotation, momentum |
| P3 | Top Swing Trade Setups | Steph | Breakout, momentum, gap setups |
| P4 | Bond & Interest Rate | Steph | Treasury yields, rate forecast |
| P5 | Tax Loss Harvesting | Alex | Wash sale, year-end strategies |

### Search Cascade (per topic)

1. **Saved Google search URLs** → extract query → YouTube API search (10 results each)
2. **YouTube Data API v3** → search + transcript fetch (4-method: cookies, API, timedtext, yt-dlp)
3. **Google News RSS** → free, 10 results per query
4. **Brave Search News** → if API key active
5. **DuckDuckGo HTML** → last resort, no key needed

### Entity Linking

When content has no ticker, it links by topic/sector/concept:
- SSDI article → `entity_type='topic', entity_value='ssdi'`
- NVDA datacenter article → `entity_type='ticker', entity_value='NVDA'` AND `entity_type='sector', entity_value='ai_infrastructure'`
- Retirement planning → `entity_type='topic', entity_value='retirement_planning'`

Entity links enable cross-system queries: "Show me everything about NVDA" returns trade proposals AND topic intelligence articles.

### Access Points

| Channel | Path |
|---------|------|
| Command Center | `/v2/topic-monitor` |
| Telegram | `topic status`, `topic add`, `topic url`, `topic run` |
| API | `/api/v2/topics`, `/api/v2/topics/by-ticker/{TICKER}`, `/api/v2/topics/entities` |
| Agents | Automatic via RAG + entity links + agent_event_queue |

### Daily API Cost

| Source | Calls/Day | Cost |
|--------|-----------|------|
| YouTube Data API v3 | ~34 searches (3,400 of 10,000 free quota) | Free |
| Google News RSS | ~51 fetches | Free |
| YouTube transcript API | ~50 transcripts | Free |
| Brave Search (if renewed) | ~34 queries | ~$0.17/day ($5/mo) |
| Local LLM (curation) | ~67 calls, ~17 min GPU | ~$0.02 electricity |
| Cloud LLM fallback | Rare | ~$0.01/day |
| **Total** | | **Free-$0.20/day** |

### Cron Schedule

| Time | Script | Purpose |
|------|--------|---------|
| 6:45 AM M-F | `topic_ingestion.py --gaps-only --no-llm` | Fill gaps, fast |
| 7:00 AM M-F | `topic_curator.py --improve-queries` | Rate, extract, link, improve |
| 8:00 PM Sunday | `topic_ingestion.py` | Full run, all topics, with LLM |

---

## 7. Screener System

- **Source:** Finviz Elite (requires active subscription + cookie)
- **Config:** `assets/screeners.yaml`
- **Authentication:** Dual method (cookie for scraping + API token for API calls)

### Active Screeners

| Screener | RVOL | Gap | Price | Float |
|----------|------|-----|-------|-------|
| `prime_setups` | >5x | >10% | $2-$20 | <50M |
| `watchlist_setups` | >3x | >5% | $1-$30 | <100M |

### Run Windows

| Window | Time | Purpose |
|--------|------|---------|
| 1 | 04:00 AM | Pre-market scan (European hours) |
| 2 | 07:00 AM | Pre-market US hours |
| 3 | 09:00 AM | Market open |
| 4 | 10:00 AM | Post-open consolidation |

---

## 8. Strategy Engine

All 20 strategies are loaded dynamically from `config/strategies/*.yaml` at runtime. There are no hardcoded strategy lists anywhere in the codebase.

### Strategy Classification Flow

```
Symbol from screener/incubator
    |
    v
Phase 1: Deterministic Filters
(screen_filters from YAML + enrichment data)
    |
    +-- match --> Assign matched strategies
    |
    +-- no match --> Phase 2: LLM Classification
                     (qwen3:14b thesis-driven)
                         |
                         v
                     Assign thesis-driven strategies
    |
    v
Multi-Strategy Assignment
(single symbol can match multiple strategies)
    |
    v
Write to incubator_universe
```

### Strategies by Timeframe

| Timeframe | Strategies |
|-----------|------------|
| **INTRADAY** | `gap_and_go`, `momentum_scalp` |
| **SHORT_SWING** | `earnings_catalyst`, `swing_breakout`, `swing_trade`, `speculative_growth`, `tax_loss_harvest` |
| **MEDIUM_SWING** | `recovery_watch`, `sector_rotation` |
| **POSITION** | `income_add`, `core_growth_compounder`, `core_index`, `covered_call_income`, `defense_thesis`, `dividend_growth_compounder`, `high_yield_income_bdc`, `international_dividend`, `reit_income`, `bond_income` |
| **CASH** | `cash_or_stable` |

Each YAML strategy defines: entry criteria, risk parameters (position size, stop placement), scoring weights, exit rules, account eligibility, and co-enablement rules.

**14 of 20 strategies require LLM classification** (IV rank, dividend growth years, unrealized losses not available in the deterministic enrichment cache).

---

## 9. Incubator Pipeline

The incubator is the holding area between raw screener hits and actionable proposals.

### Stage Flow

1. **`weekly_incubator_builder`** (Sunday 7 PM) -- Pulls qualified tickers from `trade_ai_scans` (score >= 30, RVOL >= 3, catalyst verified). Classifies each against all 20 strategies.

2. **`daily_incubator_refresh`** (daily) -- Updates scores, RVOL, and catalyst freshness.

3. **`incubator_rolloff_engine`** -- Removes symbols that no longer meet criteria.

4. **`incubator_llm_screener`** (NEW) -- Pre-promotion LLM screening for quality control.

5. **`incubator_proposal_promoter`** (8:20 AM + 6:10 PM M-F) -- Promotes qualifying symbols.

### Promotion Criteria

| Condition | Requirements |
|-----------|--------------|
| High-conviction | `status=ACTIVE`, `score >= 38`, `catalyst_verified = true`, `days_active >= 1` |
| Score override | `status=ACTIVE`, `score >= 45`, `days_active >= 1` |

---

## 10. Proposal Lifecycle & Automated Execution

### Lifecycle Flow

```
[PROPOSED] ──→ [ENRICHING] ──→ [RISK_CHECK] ──→ [PENDING]
                                                     │
                    ┌────────────────────────────────┤
                    │                                │
               [APPROVED]                       [REJECTED / RISK_BLOCKED / EXPIRED]
                    │
                    │ ← INSTANT (same HTTP request, no cron delay)
                    ▼
            [ALPACA SUBMISSION]
                    │
        ┌───────────┼───────────┐
        │           │           │
   [MARKET]    [LIMIT]    [BRACKET]
   (immediate)  (wait)    (limit+stop+target)
        │           │           │
        ▼           ▼           ▼
     [FILLED]  [PENDING_FILL] [PENDING_FILL]
        │                       │
        ▼                       ▼
     [OPEN] ←──────────────────┘
        │
        │  ← paper_trade_monitor.py (every 5 min)
        │     adjusts stops, checks targets
        ▼
     [CLOSED]
     (target hit / stop hit / manual close)
```

**Key principle:** Approval triggers immediate execution. There is no human step between approval and Alpaca order submission. The system determines order type, parameters, and routing automatically.

### Order Type Selection Logic

The system selects order type at submission time based on current market conditions:

```
Adapter checks current Alpaca quote for the symbol
    │
    ├─ Current price ≤ proposed entry      → MARKET ORDER
    │   (Better price available — fill now)
    │
    ├─ Current price within 2% of entry    → MARKET ORDER
    │   (Close enough — avoid missing the setup)
    │
    └─ Current price >2% above entry       → LIMIT ORDER (bracket)
        (Price drifted — wait for value)      limit buy + stop loss + take profit
```

Market orders: submitted as simple buy, stop placed separately after fill (GTC).
Limit orders: submitted as bracket (buy + stop + target as OCA group).

### Risk Gate (Pre-Submission)

Every proposal passes through `risk_gate.py` before execution:

| Check | Threshold | Fail Action |
|-------|-----------|-------------|
| Position size | Paper: $15K max (env configurable), Live: per strategy YAML | DOLLAR_SIZE_TOO_LARGE |
| Duplicate position | No open trade for same symbol | BLOCKED_DUPLICATE |
| Duplicate order | Idempotency check via client_order_id | BLOCKED_DUPLICATE_ORDER |
| Quality review | Not in BLOCKED_BY_RISK_GATE or REJECT_RECOMMENDED | BLOCKED_QUALITY |
| Live trading lock | ALPACA_MODE must be 'paper' | BLOCKED_LIVE_MODE |
| Data quality | Intel readiness > 50 (warning only) | LOW_INTEL (warning) |

### Execution-Time Revalidation

Before submitting to Alpaca, `paper_execution_revalidator.py` runs a final check:

| Check | Action |
|-------|--------|
| Market session (closed/premarket/afterhours) | Delay until regular hours |
| Recommendation staleness (vs strategy-specific threshold) | Delay or downgrade |
| Approval staleness | Delay if approved too long ago |
| Price drift from proposed entry | Warn or block if drift > threshold |
| Material changes since approval | Require re-approval |

Freshness thresholds match strategy timeframe:

| Strategy Type | Staleness Threshold |
|--------------|-------------------|
| Scalp / gap_and_go | 30 minutes |
| Momentum / day trade | 60 minutes |
| Swing / swing_breakout | 3 days (4,320 min) |
| Earnings / sector rotation | 5 days (7,200 min) |
| Income / position / defense | 10 days (14,400 min) |

Staleness is checked against `approved_at` (when user acted), not `created_at` (when system generated).

### Proposal Enrichment Packet

Each proposal accumulates before becoming submittable:
- Entry/stop/target price levels (from ATR, confluence cache, or strategy rules)
- Catalyst data and verification
- Indicator confluence (17 technical indicators)
- Agent analysis results (if reviewed)
- Risk gate assessment
- LLM review (when available)

### In-Trade Position Management

Once a position is open on Alpaca, `paper_trade_monitor.py` runs every 5 minutes during market hours and manages the position automatically:

#### R-Multiple Trailing Stop System

The R-multiple is the strategy's risk-to-reward framework in action. R = (current_price - entry) / initial_risk.

| Condition | Action | Logic |
|-----------|--------|-------|
| R < 1.0 | Hold — stop at original level | Trade hasn't proven itself yet |
| R >= 1.0 | Move stop to breakeven (entry price) | Eliminate risk — free trade |
| R >= 1.5 | Lock 0.5R profit | Protect partial gain |
| R >= 2.0 | Lock 1.0R profit | Protect full initial risk as profit |
| R >= 3.0 | Lock 2.0R profit (tight trail) | Aggressive profit protection |
| 80%+ of target move | Tighten stop to lock 65% of gain | Near-target protection |
| Price >= target_1 | Close position at market | Take profit |

**Stops only move UP, never down.** The trailing stop ratchets upward as the trade progresses.

#### Dynamic Stop Adjustment Flow

```
paper_trade_monitor.py (every 5 min, market hours)
    │
    ├─ Fetch all positions from Alpaca
    ├─ For each position:
    │   ├─ Get current price from Alpaca
    │   ├─ Get entry/stop/target from paper_trades DB
    │   ├─ Compute R-multiple
    │   ├─ Get current stop order from Alpaca
    │   │
    │   ├─ If target hit:
    │   │   ├─ Cancel stop order on Alpaca
    │   │   ├─ Close position at market
    │   │   ├─ Update paper_trades: status=closed, exit_price, pnl, r_multiple
    │   │   └─ Send Telegram alert: "TARGET HIT"
    │   │
    │   ├─ If R crossed a threshold:
    │   │   ├─ Compute new stop price
    │   │   ├─ If new_stop > current_stop:
    │   │   │   ├─ Cancel old stop on Alpaca
    │   │   │   ├─ Place new stop (GTC)
    │   │   │   ├─ Update paper_trades.stop_loss
    │   │   │   └─ Send Telegram alert: "Stop adjusted"
    │   │   └─ Else: hold (stops never move down)
    │   │
    │   ├─ If near target (80%+ of move):
    │   │   └─ Tighten stop to lock 65% of gain
    │   │
    │   └─ Update paper_trades: current_price, r_multiple, pnl
    │
    └─ Send consolidated Telegram alert if any actions taken
```

#### Alpaca Order Limitations

Alpaca paper trading does not support simultaneous stop + limit sell on the same shares (OCA). The workaround:
- Stop-loss is placed as a standing GTC order on Alpaca
- Profit target is monitored by `paper_trade_monitor.py` every 5 minutes
- When price reaches 80%+ of target move, the stop tightens aggressively to capture the gain
- When target is hit, the stop is cancelled and position is closed at market

#### Safety Net

`paper_execution_sweep.py` runs every 5 minutes during market hours as a safety net:
- Finds approved proposals with `paper_submit_state = NOT_SUBMITTED`
- Calls `submit_paper()` for each
- Catches edge cases: server restart during approval, network blip, etc.

This is NOT the primary execution path — instant execution on approval is. The sweep is the fallback.

---

## 11. Agent Layer

### Conversational Agents (OpenClaw Gateway :18789)

| Agent | Role | Key Capabilities |
|-------|------|-------------------|
| **Maria** | Risk assessment | Position sizing, portfolio impact, exposure analysis, correlation checks |
| **Steph** | Technical analysis | Entry/exit timing, chart patterns, wealth advisory, indicator confluence |
| **Aegis** | Synthesis & surveillance | Nightly synthesis, morning briefs, cross-agent coordination, overnight monitoring |
| **Alex** | Income strategy | Roth conversion planning, SSDI/IRMAA impact, dividend analysis, covered call evaluation |

Agents are accessible via Telegram and WhatsApp. Configuration is in `config/agents.yaml` and personality/behavior rules in the agents bible (`docs/project/agents_bible.md`).

### Backend Automation Agents

| Agent | Role | Script |
|-------|------|--------|
| **Iris** | Library hygiene -- content quality, stale data detection, dependency audits | `scripts/iris_*.py` |
| **Pipeline Watchdog** | Health monitoring -- 31 stage failure/delay detection | `scripts/pipeline_watchdog.py` |
| **Scalp Critic** | LLM critique of screener candidates before promotion | `scripts/incubator_llm_screener.py` |

### Agent Processing Schedule

| Window | Interval | Jobs/Run | Context |
|--------|----------|----------|---------|
| Market hours (6 AM - 7 PM) | Every 15 min | 10 jobs | Active trading context |
| Overnight (8 PM - 11 PM) | Every 5 min | 25 jobs | Batch processing |
| Weekend | Every 10 min | 15 jobs | Catch-up processing |

---

## 12. LLM Subsystem

### Configuration

All LLM config is sourced from `.env` -- zero hardcoded values. Configuration hub: `scripts/local_llm_config.py`.

### Primary Model

| Parameter | Value |
|-----------|-------|
| Model | `qwen3:14b` |
| Runtime | Ollama (localhost:11434) |
| GPU | Intel Arc B50 (Vulkan backend) |
| Layer offload | 41/41 layers on GPU |
| Keep-alive | Persistent (`OLLAMA_KEEP_ALIVE=-1`) |
| Performance | ~15s per chunk (GPU) vs ~300s (CPU) |

### Routing & Fallback Chain

```
local (qwen3:14b via Ollama) ──→ OpenAI (gpt-4o-mini) ──→ Anthropic (claude-sonnet-4-6)
         PRIMARY                      FALLBACK 1                  FALLBACK 2
    Intel Arc B50 GPU               On Ollama failure            On OpenAI failure
    ~15s/chunk, free                ~$0.01/call                  ~$0.03/call
```

**Escalation logic** (in `local_llm.py`):
- Try local Ollama first (toll-gated, max 300s timeout)
- On timeout/failure → try OpenAI `gpt-4o-mini`
- On OpenAI failure → try Anthropic `claude-sonnet-4-6`
- On all failure → return empty (caller handles gracefully)

**When external LLM is used instead of local:**
- `portfolio_yaml_advisor.py` — requires Claude Opus (complex multi-page analysis). Currently blocked by API credit depletion.
- Agent conversational responses (via OpenClaw) — may use cloud LLM for complex queries
- All other use cases (classification, screening, enrichment, narratives) → local primary

### Toll Gate (GPU Contention Prevention)

File lock at `/tmp/ollama_llm_gate.lock` using `fcntl.flock(LOCK_EX)`:
1. Caller acquires exclusive lock (blocks up to 600s)
2. Writes PID + timestamp to lock file for debugging
3. Sends request to Ollama
4. Releases lock on completion or timeout
5. If lock acquisition fails → falls back to cloud LLM

### LLM Use Cases

| Use Case | Script | Frequency | Model |
|----------|--------|-----------|-------|
| Intelligence enrichment (5 surfaces) | `llm_intelligence_enrichment.py` | 7:20 AM daily | qwen3:14b |
| Strategy classification (23 strategies) | `multi_strategy_classifier.py` | Sunday night batch | qwen3:14b |
| Proposal review (4-chunk pipeline) | `proposal_llm_reviewer.py` | Per proposal | qwen3:14b |
| Incubator pre-screening (A-F grades) | `incubator_llm_screener.py` | 8:10 AM + 6 PM | qwen3:14b |
| Holdings health refresh | `holdings_llm_refresh.py` | 3x daily market hours | qwen3:14b |
| Topic curation (rate, extract, improve) | `topic_curator.py` | 7:00 AM daily | qwen3:14b |
| Agent responses | Via OpenClaw gateway | On user interaction | qwen3:14b + cloud fallback |
| Rebalance advisor | `portfolio_yaml_advisor.py` | Monthly or on-demand | Claude Opus (cloud) |

### LLM Intelligence Enrichment (Phase 5)

`llm_intelligence_enrichment.py` generates 5 intelligence sections daily, stored in `llm_intelligence_cache`:

| Section | Content | Surfaced On |
|---------|---------|-------------|
| `portfolio_risk` | Risk assessment narrative (concentration, stops, actions) | `/v2/command` |
| `rebalance_suggestions` | 5 numbered tax-aware suggestions | `/v2/rebalance` |
| `recovery_analysis` | Re-entry readiness and abandonment calls | `/v2/recovery` |
| `morning_synthesis` | Portfolio + news + social synthesis paragraph | `/v2/command`, Overview |
| `prospect_narratives` | Per-symbol 1-sentence thesis (top scored) | `/v2/prospects` |
| **Topic query generation** | `topic_ingestion.py --curate` | Per ingestion run |
| **Content quality rating** | `topic_curator.py` | Post-ingestion |
| **Entity extraction (tickers/topics/sectors)** | `topic_curator.py` | Post-ingestion |
| **Query improvement (learning loop)** | `topic_curator.py --improve-queries` | Daily |

---

## 13. API Layer

- **Endpoint count:** 100+
- **Base path:** `/api/v2/*`
- **Server:** `scripts/portfolio_server.py` on port 7777
- **Handler:** `scripts/api_v2.py` (12,600+ lines)
- **Protocol:** HTTP/JSON (no auth layer -- internal network only)

### Endpoint Groups

| Group | Key Endpoints | Methods |
|-------|--------------|---------|
| **Portfolio** | `portfolio/holdings`, `portfolio/performance`, `portfolio-monitor` | GET |
| **Watchlist** | `watchlist`, `watchlist/items`, `watchlist/symbols`, `watchlist/research-card/{sym}` | GET, POST |
| **Prospects** | `prospects`, `trade-ai` | GET |
| **Proposals** | `proposals`, `proposals/feedback`, `proposals/history`, `proposal-detail/{id}` | GET, POST, PUT |
| **Intelligence** | `intelligence-entities`, `intelligence-whiteboard`, `qualified-intelligence` | GET |
| **CIO** | `cio` (unified), `cio-dashboard`, `cio-decisions`, `cio-decisions/{sym}` | GET |
| **Recovery** | `recovery` (exit classification, relist tracking, patience scoring) | GET |
| **Rebalance** | `rebalance`, `rebalance-plans`, `rebalance-plans/latest` | GET |
| **Reports** | `reports` (hub), `weekly-report`, `monthly-report` | GET |
| **Retirement** | `retirement`, `tax-situation`, `trust-transfers` | GET |
| **Strategy** | `strategy-rules`, `strategy-rotations`, `classifications` | GET, PUT |
| **Agents** | `agent-pipeline`, `agent-health`, `agent-detail`, `agent-calibration` | GET |
| **Risk** | `risk-gate-status`, `portfolio-signal-qa` | GET |
| **Research** | `rag/status`, `research/ticker/{sym}`, `research-topics` | GET, POST |
| **Social** | `social/posts`, `social/status`, `aegis/social-sentiment` | GET |
| **Pipeline** | `pipeline-health`, `pipeline-run-health`, `auto-proposal-diagnostics` | GET |
| **System** | `system-health`, `cost-dashboard`, `llm/health`, `llm-spend` | GET |

### New Endpoints (Session 29 — 2026-05-11)

| Endpoint | Purpose |
|----------|---------|
| `/api/v2/recovery` | Full recovery dashboard with exit classification (true stop-out vs relist vs market reconnection), patience scoring, relist event history |
| `/api/v2/cio` | Unified CIO intelligence with deduplicated decisions (DISTINCT ON symbol), rotations, plans, learning recommendations |
| `/api/v2/portfolio-monitor` | Real-time portfolio health: holdings with technicals, risk alerts, news digest, LLM health, dividend calendar, recovery watch |
| `/api/v2/reports` | Reports hub: agent activity, pipeline runs, learning stats, incubator, social ingestion, weekly DOCX catalog |

### Enrichment Changes (Session 29)

- **`/api/v2/prospects`**: Now includes incubator LLM screen grades, proposal LLM reviews, social sentiment from `social_sentiment_history`
- **`/api/v2/watchlist`**: Now includes LLM health, news counts (7d), social sentiment, latest scan scores/decisions, catalyst text

---

## 14. Frontend

- **Framework:** React SPA (Next.js)
- **Route:** served at `/v2/` via Portfolio Server (port 7777)
- **Source:** `apps/command-center-v2/` (91 TypeScript/React files)
- **Pages:** 61 (all fully implemented, no stubs)
- **API hooks:** `useApi()`, `useFetch()` custom hooks for data fetching
- **Charts:** BarChartJS, LineChart, DoughnutChart components

### Page Groups

| Group | Pages | Key Views |
|-------|-------|-----------|
| **Portfolio Core** | Overview, Portfolio, Returns, Dividends, Rebalance, Retirement, Tax, Correlation, Attribution, Forecast | Holdings, P&L, income, allocation, tax lots |
| **Trading** | Trade AI, Strategy Desk, Prospects, Execution Quality, Broker Recon | Screener results, strategy signals, TCA |
| **Paper Trading** | Paper Status, Paper Proposals, Paper Journal, Paper Outcomes, Paper Governance, Paper Trade Intelligence | Full paper trading lifecycle |
| **Intelligence** | AI Analyst, Intelligence Sources, Intelligence Entities, Intelligence Whiteboard, Content Health, Topic Monitor, Portfolio Intelligence | Research, NLP, RAG, topic ingestion |
| **Agents** | Agent Pipeline, Agent Calibration, CIO Dashboard, Morning Brief | Agent performance, decisions, briefings |
| **Monitoring** | Watchlist, Recovery, Portfolio Monitor, Alerts, Notifications, System Health, Risk, Risk Regime | Position tracking, stops, alerts |
| **Pipeline** | Pipeline Health Master, Pipeline Controller, Incubator, Self Improvement, Weekly Learning, Learning Governance | Pipeline ops, incubator lifecycle |
| **Reporting** | Reports, Journal Analytics, Journal Reports, Backtesting | Analytics, reports, DOCX catalog |
| **Admin** | Strategy Admin, Live Governance, Approvals, Orchestration, Ops, System Hub, Action Center | Config, governance, operations |

---

## 15. Notification & Alerting

| Channel | Integration | Config | Priority |
|---------|-------------|--------|----------|
| **Telegram** (primary) | Bot API | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | P1 -- all alerts |
| **WhatsApp** | Twilio API | Twilio credentials | P2 -- agent conversations |
| **Email** | SMTP | SMTP config | P3 -- reports |
| **Slack** | Webhook | Webhook URL | P4 -- optional |

All channels toggled via `ENABLE_*` flags in `.env`.

### Alert Types

| Alert | Source | Trigger |
|-------|--------|---------|
| Smart Proactive Alerts | `telegram_smart_alerts.py` | 6 AM daily |
| Pipeline Failure (watchdog) | `pipeline_watchdog.py` | Stage failure/staleness |
| Pipeline Failure (wrapper) | `pipeline_alert.py` | Non-zero exit on any wrapped cron job |
| System Health | `system_health_alerts.py` | Threshold breach |
| Iris Library Alert | Iris agent | Content hygiene issues |
| Aegis Morning Brief | `aegis_morning_brief_delivery.py` | 8 AM daily |
| Recovery Watch | `recovery_watch_daily.py` | Stop-out detection, relist classification, escalation to Maria/Steph |
| Pre-Market StockTwits | `premarket_watcher.py` | StockTwits surge data (persisted to social_posts + trade_ai_scans) |
| Stop Placement Reminder | `recovery_watch_daily.py` | Positions without confirmed stops |
| Weekly DOCX Report | `generate_weekly_docx.py` | Weekly Word report generated + Telegram notification |
| Intelligence Gap Fill | `agent_event_router.py` | CONTENT_GAP auto-search completion |
| Incubator Promoter | `incubator_proposal_promoter.py` | Promotions or failures |
| YouTube Ingestion | `youtube_transcript_ingest.py` | Crash during channel scan |

### Pipeline Failure Alerting (Session 37)

Every critical cron job is wrapped with `pipeline_alert.py` which:
1. Runs the command and captures stdout/stderr
2. On non-zero exit: sends Telegram with error excerpt + reply-to-retry command
3. Logs to `logs/<pipeline_name>.log` with timestamp and exit code

Wrapped pipelines: news_ingestion, youtube_ingest, overnight_batch, sec_data_ingest, event_detector, previously_traded, pipeline_watchdog.

**Scale:** 56 scripts send Telegram alerts across 100+ unique call sites. All sends logged to `notification_log` table with dedupe keys.

### Central Alert Dispatcher (Phase 2)

`alert_dispatcher.py` provides unified routing for all alerts:

| Feature | Detail |
|---------|--------|
| **Cross-script dedup** | Same symbol + alert type + date = one alert per day |
| **Escalation tiers** | `INFO` (dashboard only), `ALERT` (Telegram), `URGENT` (bypasses rate limit) |
| **Fatigue detection** | Auto-downgrade to INFO after 3 consecutive days + fire META alert |
| **Rate limiting** | Max 15 Telegram alerts per hour (configurable via `ALERT_MAX_PER_HOUR`) |
| **Convenience functions** | `alert_stop_triggered()`, `alert_dividend_payers()`, `alert_pipeline_failure()`, `alert_proposal_aging()`, `alert_api_credits_depleted()` |

### Missing Condition Alerts (Phase 2)

`alert_missing_conditions.py` checks daily at 7:30 AM:
- Proposals stuck in PENDING > 7 days
- Anthropic API credit depletion (minimal POST test)
- Email digest not firing > 3 days
- Rebalance data > 14 days stale

**Telegram reply commands for retry:**
- `run promoter` / `run promoter dry` — retry incubator promoter
- `run screener <name>` — retry a screener
- `status` — full system health check

### Failure Notification Flow

```
Cron fires script via pipeline_alert.py
    ↓
Script exits non-zero
    ↓
pipeline_alert.py captures error
    ↓
Telegram alert sent:
    "PIPELINE FAILURE: <name>
     Error: <last 5 lines>
     Reply: run <name>"
    ↓
John replies in Telegram → telegram_command_handler executes retry
```

---

## 16. Scheduling & Orchestration

53 cron entries manage the full pipeline (flock-protected to prevent stacking). Key schedule (all times Eastern):

### Morning Cascade (5-8 AM)

| Time | Job | Script |
|------|-----|--------|
| 5:00 AM | Alex daily scan | `alex_retirement_advisor.py` |
| 5:45 AM | Indicator cache refresh | `indicator_cache_refresh.py` |
| 6:00 AM | Smart proactive alerts | `telegram_smart_alerts.py` |
| 6:15 AM | Agent context refresh | `agent_context_refresh.py` |
| 6:25 AM | Agent intelligence discovery | `agent_intelligence.py` |
| 6:30 AM | News ingestion | `news_ingestion.py` |
| 6:45 AM | Topic ingestion (gaps only) | `topic_ingestion.py --gaps-only` |
| 6:35 AM | Classify candidates | `multi_strategy_classifier.py` |
| 6:45 AM | Sync watchlist to DB | `watchlist_sync.py` |
| 6:50 AM | Materialize strategy cards | `strategy_card_materializer.py` |
| 6:55 AM | Income engine | `income_engine.py` |
| 7:00 AM | CIO decisions + enrichment | `cio_decision_engine.py` |
| 7:00 AM | Topic curator (rate, extract, improve) | `topic_curator.py --improve-queries` |
| 7:15 AM | State freshness + price sync | `state_freshness_writer.py` |
| 7:15 AM | Portfolio orchestrator (digest, alerts) | `portfolio_orchestrator.py` |
| 7:20 AM | LLM intelligence enrichment (5 sections) | `llm_intelligence_enrichment.py` |
| 7:25 AM | System health alerts | `system_health_alerts.py` |
| 7:30 AM | Missing condition alerts | `alert_missing_conditions.py` |
| 7:40 AM | Portfolio QA | `portfolio_level_qa.py` |
| 8:00 AM | Aegis morning brief (upgraded: dividends, proposals, risk) | `aegis_morning_brief_delivery.py` |

### Market Hours (9 AM - 4 PM)

| Time | Job |
|------|-----|
| 09:00, 10:00 AM | Orchestrator runs (screener windows 3, 4) |
| 11, 12:30, 1, 2, 3 PM | Hourly light reprice + intraday intelligence |
| 12:30 PM | News ingestion (midday) |
| 4:00 PM | End-of-day screener + news |

### Evening & Overnight

| Time | Job |
|------|-----|
| 6:10 PM | Proposal promoter (evening) |
| 8:00 PM | Overnight batch + SEC Form 4 |
| 8:30 PM | Feedback loop processor (outcome chains, alert scoring) |
| 9:00 PM | Auto-research |
| Sun 7:00 PM | Weekly incubator builder |
| Sun 8:00 PM | Full topic ingestion (all topics, with LLM) |
| Sun 9:00 PM | Weekly DOCX report (`generate_weekly_docx.py`) |
| Sun 10:00 PM | LLM incubator classification |
| 1st of month, 6 AM | Backup verification (`backup_verify.py`) |

---

## 17. Security & Access Control

### Current State (Self-Hosted)

| Layer | Control |
|-------|---------|
| **Network** | Server on private network; no public-facing ports |
| **API** | No authentication layer (internal-only access) |
| **Database** | Password authentication, localhost-only binding |
| **Secrets** | `.env` file (not in git, `.gitignore` enforced) |
| **LLM** | Local inference primary; cloud API keys in `.env` |
| **Broker** | Paper mode only; API keys scoped to paper trading |

### Cloud Migration Security Requirements

| Requirement | Implementation |
|-------------|---------------|
| API authentication | API Gateway + JWT / API key |
| Network isolation | VPC + private subnets for DB and LLM |
| Secrets management | AWS Secrets Manager / Azure Key Vault |
| TLS everywhere | ALB/App Gateway termination + internal TLS |
| Audit logging | CloudTrail / Azure Monitor |
| RBAC | IAM roles per service |

---

## 18. Failure Modes & Recovery

### Critical Failure Scenarios

| Failure | Impact | Detection | Recovery |
|---------|--------|-----------|----------|
| **PostgreSQL down** | All services halt | `pg_isready` + watchdog | Restart service; restore from 7-day rolling backup |
| **Ollama crash** | LLM classification stops | Health check on `:11434` | Systemd auto-restart; cloud fallback activates |
| **Portfolio Server crash** | API + frontend unavailable | Health check on `:7777` | `pkill + restart`; systemd auto-restart |
| **Finviz cookie expired** | No new screener candidates | Screener stage reports 0 results | Manual browser re-authentication |
| **Cloud LLM budget exhausted** | Falls back to next provider | Budget counter in `.env` | Resets daily; or increase budget |
| **Network outage** | External data sources unavailable | Source staleness exceeds threshold | Pipeline operates on cached data; alerts operator |
| **Disk full** | Logs/backups fill disk | Disk monitoring | Log rotation; backup pruning |
| **GPU driver issue** | LLM falls back to CPU (~20x slower) | Vulkan layer count check | Restart Ollama with override; verify `OLLAMA_VULKAN=1` |

### Backup Strategy

| Asset | Method | Retention | Location |
|-------|--------|-----------|----------|
| Database | `pg_dump` (gzipped) | 7-day rolling | `backups/db/` |
| Configuration | `.env` + strategy YAML snapshot | Per-session | `backups/session*/` |
| Source code | Git | Full history | `.git/` |
| Portfolio state | JSON snapshot | 10 daily snapshots | `data/portfolios/snapshots/` |
| Systemd services | Config backup | Per-change | `backups/systemd/` |

### Recovery Procedures

Full disaster recovery documented in `docs/RESTORE_GUIDE.md`:
- 6 core services to restore
- 23-point preflight check
- DB restore sequence
- Cron re-installation
- OpenClaw reconfiguration

---

## 19. Safety Rules (Non-Negotiable)

These rules are non-negotiable. No automation, agent, or operator override may violate them.

| # | Rule | Enforcement |
|---|------|-------------|
| 1 | `LIVE_TRADING_ENABLED=false` -- never change | `.env` + code assertion |
| 2 | `ALPACA_MODE=paper` -- never change | `.env` + adapter check |
| 3 | No risk gate threshold changes without explicit owner approval | UI gate + audit log |
| 4 | No auto-approval of proposals -- human-in-the-loop required | Proposal state machine |
| 5 | No holdings modification by automation | Read-only portfolio access |
| 6 | Holdings value must remain > $1M | Assertion check in code |

**Validation gate:** Live trading will not be enabled until:
- 6-month paper validation window closes (~Nov 2026)
- Win rate >= 55%
- Profit factor >= 1.3
- Full governance review completed

---

## 20. Key File Locations

| Path | Purpose |
|------|---------|
| `.env` | All secrets, API keys, feature flags |
| `.env.example` | Template with all variables documented |
| `config/strategies/*.yaml` | 20 strategy definitions (loaded dynamically) |
| `assets/screeners.yaml` | Finviz screener URLs + run windows |
| `assets/portfolio_accounts.yaml` | Account definitions |
| `assets/weights.yaml` | Asset allocation weights |
| `data/portfolios/state/holdings.json` | Portfolio state (current holdings) |
| `data/portfolios/state/personal_situation.json` | Personal data (18 keys) |
| `data/state/ticker_enrichment_cache.json` | Enrichment cache (1,139 symbols) |
| `scripts/api_v2.py` | All 275+ API endpoints (13,000+ lines) |
| `scripts/portfolio_server.py` | HTTP server with token auth (1,800+ lines) |
| `scripts/portfolio_orchestrator.py` | Orchestration hub with dividend alerts (1,750+ lines) |
| `scripts/recovery_watch_daily.py` | Recovery watch with exit classification (true stop-out vs relist) |
| `scripts/generate_weekly_docx.py` | Weekly consolidated Word report from all subsystems |
| `scripts/cio_decision_engine.py` | CIO decisions with 24h dedup gate |
| `scripts/alert_dispatcher.py` | Central alert routing (dedup, tiers, fatigue, rate limit) |
| `scripts/alert_missing_conditions.py` | Daily missing condition checks (proposals, API, email, rebalance) |
| `scripts/llm_intelligence_enrichment.py` | Daily LLM narrative generation (5 sections via qwen3:14b) |
| `scripts/feedback_loop_processor.py` | Outcome chains, alert scoring, strategy snapshots, agent tracking |
| `scripts/backup_verify.py` | Monthly backup integrity verification |
| `scripts/trade_ai_orchestrator.py` | Screener + scoring (873 lines) |
| `scripts/local_llm_config.py` | LLM configuration hub |
| `scripts/local_llm.py` | Ollama inference with toll gate |
| `scripts/topic_ingestion.py` | Topic-based content ingestion (4-source cascade) |
| `scripts/topic_curator.py` | Post-ingestion curation (rate, extract, link, improve) |
| `scripts/youtube_transcript_ingest.py` | YouTube video/channel ingestion (4-method transcript fetch) |
| `scripts/telegram_command_handler.py` | Telegram command handler (add video, add article, research, etc.) |
| `sql/migrations/` | 22 SQL migration files |
| `crontab_backup.txt` | Full cron schedule backup |
| `requirements.txt` | 90 Python packages |
| `docs/RESTORE_GUIDE.md` | Disaster recovery guide |
| `docs/project/agents_bible.md` | Agent behavior rules |
| `docs/project/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md` | Strategy playbooks |

---

## 21. Known Constraints

| Constraint | Impact | Mitigation |
|------------|--------|------------|
| LLM classification speed | ~4.5 min/symbol on Intel Arc B50 (GPU) | Scheduled overnight; toll gate queuing |
| Finviz cookie expiry | Periodic manual browser authentication | Dual auth (cookie + API token); alert on 0-result scans |
| yfinance rate limits | ~2-3s throttle per symbol | Batch processing with delays |
| LLM-only strategies | 14/20 strategies need LLM (data not in enrichment cache) | Scheduled overnight batch |
| Proposal enrichment latency | ~30s-1min per proposal | Chunked async state machine |
| Single-server deployment | No HA, single point of failure | 7-day rolling pg_dump; documented restore guide |
| API authentication | Token-based auth via `API_AUTH_TOKEN` in .env | Set token to enable; frontend exempt; all /api/ paths checked |
| Anthropic API credits depleted | Rebalance advisor (`portfolio_yaml_advisor.py`) cannot refresh | Requires credit top-up or local LLM fallback |
| CIO daily duplicate decisions | Same symbol+action generated daily | 24h dedup gate added to `cio_decision_engine.py` |
| StockTwits pre-market persistence | Was Telegram-only, invisible to dashboard | Fixed: now writes to `social_posts`, `trade_ai_scans`, `scalp_scan_results` |
| Alpaca OCA limitation | Cannot hold stop + target orders simultaneously on same shares | Target monitored by `paper_trade_monitor.py` every 5 min; at 80% of move, stop tightens aggressively |
| Paper trading validation period | 6-month window required before live trading | Live trading gate tracks 4 metrics; all currently FAIL |

---

## 22. Glossary

| Term | Definition |
|------|------------|
| GO | Screener decision: symbol qualifies for trading |
| WAIT | Screener decision: monitor but do not trade |
| NO-GO | Screener decision: disqualified |
| RVOL | Relative volume vs. 20-day average |
| ATR | Average true range (14-period) |
| R:R | Risk-to-reward ratio |
| TCA | Transaction cost analysis |
| ENTRY_MISSED | Price moved beyond the defined entry zone |
| ENTRY_ZONE_VALID | Price is still within tradeable entry range |
| Pipeline chevron | Visual 8-stage progress indicator for proposals |
| Toll gate | `fcntl.flock()` serialization for GPU access |
| Incubator | Holding area between screener hits and proposals |
| Enrichment cache | Pre-computed Finviz + fundamental data per symbol |
| Strategy YAML | Dynamic strategy definition file loaded at runtime |
| Paper mode | All trades executed on Alpaca paper (simulated) |
| Profit factor | Gross profit / gross loss ratio |
| Relist | Vehicle/symbol reappears in portfolio without a confirmed exit -- market behavior, not strategy failure |
| Patience score | Accumulated score for relisted positions (0.0-1.0) -- higher = more sustained engagement without exit |
| Exit classification | Categorization of stop events: true_stop_out, relist_no_exit, market_reconnection, unclassified |

---

## 23. Automation Intent & Production Readiness

### System Design Intent

Trade AI v12 is designed as a **fully automated profit-seeking trading system** with professional risk controls. The system is intended to:

1. **Discover** candidates automatically (screeners, incubator, social, news)
2. **Evaluate** them through multi-strategy scoring, agent analysis, and LLM review
3. **Propose** trades with computed entry/stop/target levels
4. **Execute** instantly on approval — system determines order type and parameters
5. **Manage** open positions automatically — trailing stops, profit targets, dynamic adjustment
6. **Close** positions on target hit or stop trigger — no manual intervention required
7. **Learn** from outcomes — feed P&L back to agent calibration and strategy scoring

Human intervention points: proposal approval (go/no-go decision) and system configuration. Everything else is automated.

Currently in **paper-only validation mode** (6-month validation window before live consideration).

### Live Trading Gate

Live trading is locked behind 4 gates (all must pass simultaneously):

| Gate | Requirement | Current | Status |
|------|------------|---------|--------|
| Win Rate | >= 55% | ~0% (3 closed) | NOT MET |
| Profit Factor | >= 1.3 | 0.0 (insufficient data) | NOT MET |
| Sample Size | >= 30 closed trades | 3 | NOT MET |
| Time in Paper | >= 6 months | ~1 month | NOT MET |

Gate status is available at `/api/v2/live-trading-gate`.

### API Authentication

- **Method:** Bearer token via `API_AUTH_TOKEN` environment variable
- **When enabled:** All `/api/*` requests require `Authorization: Bearer <token>` header
- **Exempt paths:** `/v2/` (frontend), `/data/` (state files), `/reports/`, `/api/health`
- **When not set:** Auth is disabled (open access, internal-only assumption)
- **Query param fallback:** `?token=<token>` for browser testing

### Backup Verification

- **Script:** `scripts/backup_verify.py`
- **Schedule:** Monthly (1st of month)
- **Checks:** pg_dump exists + recent, backup size non-trivial, state files fresh, DB connectivity
- **Reports:** Via Telegram alert dispatcher (severity based on findings)

### Performance Budget

| Component | Target | Notes |
|-----------|--------|-------|
| API response (p95) | < 500ms | All GET endpoints |
| Morning pipeline | 07:00 - 08:00 ET | Full cascade: data refresh → enrichment → alerts → brief |
| LLM enrichment | < 120s total | 5 sections via qwen3:14b |
| Screener full run | 10:00 AM + 4:00 PM | Weekdays only |
| Overnight batch | 8:00 - 10:00 PM | Metrics, stale refresh, agent perf |
| Weekly DOCX | Sunday 9:00 PM | After all weekly jobs |

### High Availability Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Server failure | Total outage | 7-day rolling pg_dump, restore guide, state file backups |
| GPU failure | LLM enrichment stops | Cloud fallback chain (xAI → Anthropic → OpenAI) |
| API credits depleted | Rebalance advisor unavailable | Local LLM covers most use cases, alert on depletion |
| Finviz auth failure | Screener returns 0 results | Dual auth (cookie + API token), health check alerts |
| Ollama crash | All local LLM calls fail | Auto-restart via systemd, warmup function on cold start |

---

## 24. Session Changelog

### Session 29 — 2026-05-11 (Phases 1-8)

12 commits, ~9,000 lines added across 65+ files. All changes are integrated into the sections above.

| Phase | Summary | Key Artifacts |
|-------|---------|---------------|
| **1. Fix What's Broken** | Re-entry vs stop-out classification, StockTwits pipeline fix, 4 new API endpoints, weekly DOCX, prospects entry/stop/target | `20260511_reentry_vs_stopout_classification.sql`, `generate_weekly_docx.py` |
| **2. Alert Quality** | Central alert dispatcher with dedup + fatigue + tiers, missing condition alerts, morning brief upgrade | `alert_dispatcher.py`, `alert_missing_conditions.py` |
| **3. Page Consolidation** | 61 → 42 primary routes via TabPage component. 8 merges, 3 eliminations. Legacy routes redirect. | `TabPage.tsx`, 8 hub pages, updated `App.tsx` + `Shell.tsx` |
| **4. Intelligence Delivery** | Morning Command page, market intelligence API, per-page news/social/sector context, CIO news context | `Command.tsx`, `/api/v2/command`, `/api/v2/market-intelligence` |
| **5. LLM Integration** | 5 daily intelligence sections via qwen3:14b. Portfolio risk, rebalance, recovery, morning synthesis, prospect narratives. | `llm_intelligence_enrichment.py`, `llm_intelligence_cache` table |
| **6. UI/UX** | Global alert banner (4 active alerts), freshness badges (green/yellow/red), Today's Actions panel on Overview | `GlobalAlertBanner.tsx`, `FreshnessBadge.tsx` |
| **7. Feedback Loops** | Proposal outcome chains (38 linked), alert effectiveness scoring (31 scored), strategy snapshots (4), agent sample tracking | `feedback_loop_processor.py`, `20260511_feedback_loop_closure.sql` |
| **8. Production Readiness** | API auth (token-based), backup verification (10/10 passing), live trading gate (4 gates, all FAIL = paper only) | `backup_verify.py`, `/api/v2/live-trading-gate` |
