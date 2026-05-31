# Trade AI v12 -- Architecture Overview

**Audience:** Executive / architect level
**Last updated:** 2026-05-27 (Self-healing system + broker-agnostic refactor + 8 brokers + MFE analysis)

> **STALE WARNING (2026-05-31):** This document references qwen3:14b as the primary model.
> OpenClaw agent configs still point to qwen3:14b, but it is DISABLED in .env and uninstalled
> from Ollama. Backend pipeline uses gemma3:12b (primary) / gemma3:4b (fallback). Hermes uses
> gemma3:12b. Strategy count is 24 (was 23). Full rewrite planned for a future session.

---

## What Is Trade AI v12?

Trade AI v12 is a fully automated profit-seeking trading intelligence platform that discovers, evaluates, executes, and manages equity positions against a ~$1.19M multi-account portfolio. It combines quantitative screening, 23 configurable strategies, LLM-powered analysis (5 daily intelligence sections via qwen3:14b), and 6 conversational AI agents into a single-tenant self-hosted service. Approved proposals pass through multi-layer validation (live price drift check, stop-breach gate, eligibility scoring) before conditional submission to Alpaca paper trading, with automated trailing stop management and continuous post-fill risk monitoring.

**Current state:** Self-hosted on a dedicated Linux server (`ms01-openclaw`). All services co-located. Paper trading only -- live trading locked behind a 6-month validation gate.

---

## High-Level Architecture

```
+-----------------------------------------------------------------------------------+
|                               ms01-openclaw (Linux)                                |
|                                                                                    |
|   +-----------+     +-------------+     +------------+     +------------------+    |
|   | React SPA | --> | Portfolio    | --> | PostgreSQL | <-- | Cron Scheduler   |    |
|   | (67 pgs)  |     | Server :7777|     | :5432      |     | (~190 jobs)      |    |
|   +-----------+     | 300+ APIs   |     | 392 tables |     +------------------+    |
|                     +------+------+     +------------+                              |
|                            |                                                       |
|              +-------------+-------------+-------------+                           |
|              |                           |             |                            |
|   +----------v----------+     +----------v----------+  |  +------------------+    |
|   | Ollama LLM :11434   |     | OpenClaw GW :18789  |  |  | Health Agent     |    |
|   | qwen3:14b           |     | 8 Agents            |  |  | 26 monitors      |    |
|   | Intel Arc B50 GPU   |     | (Maria/Steph/Aegis/ |  |  | 3-tier escalate: |    |
|   | 5 daily intel sects |     |  Alex/Risk/Tax/     |  |  |  Python→Claude   |    |
|   | Nightly health review|    |  Iris/MariaResearch) |  |  |  Code→LLM review |    |
|   +---------------------+     +---------------------+  |  +------------------+    |
|                                                         |                          |
|                               +-------------------------v----+                     |
|                               | Claude Code Escalation       |                     |
|                               | Auto-diagnose + fix          |                     |
|                               | Intervention log → dashboard |                     |
|                               +------------------------------+                     |
|                               +----------+----------+                              |
|                                          |                                         |
+-----------------------------------------------------------------------------------+
                                           |
              +----------------------------+----------------------------+
              |              |              |              |             |
      +-------v----+  +-----v------+  +----v-----+  +----v----+  +-----v------+
      | Finviz     |  | News APIs  |  | Alpaca   |  | Cloud   |  | Gov Data   |
      | Elite      |  | (7 srcs)   |  | (paper)  |  | LLM     |  | SEC, FRED  |
      +------------+  +------------+  +----------+  +---------+  +------------+
```

---

## Service Responsibilities

| Service | Responsibility | Scale |
|---------|---------------|-------|
| **Portfolio Server** (:7777) | Central API hub. Serves 80+ REST endpoints and the React SPA. All client-facing traffic routes through here. | 17,000+ LOC handler |
| **PostgreSQL** (:5432) | Single source of truth. All persistent state -- trades, proposals, enrichment, agent results, pipeline health. | 350+ tables |
| **Ollama LLM** (:11434) | Local inference engine. Strategy classification, proposal review, health checks. GPU-accelerated on Intel Arc B50 (Vulkan). | ~15s/chunk, toll-gated |
| **OpenClaw Gateway** (:18789) | Conversational AI routing. 6 agents accessible via Telegram + WhatsApp. Handles natural language queries about portfolio, risk, and strategy. | 6 agents |
| **Telegram Long-Poll Daemon** | Persistent background process polling Telegram for operator replies (approve/reject/stop actions). 25-second long-poll, 1-2 second reply detection. | Single daemon |
| **Cron Scheduler** | Orchestrates the 31-stage pipeline across 7 groups. Key intervals: 2-min trade monitor, 2-min proposal alerts, 5-min execution sweep. | 65+ crontab entries |
| **React SPA** | Operator dashboard. 73 pages covering portfolio, watchlist, proposals, strategy admin, risk, journal, backtesting (7 tabs). | 91 React components |

---

## Pipeline Overview (7 Groups, 31 Stages)

```
  [1. COLLECT]  >>>  [2. ENRICH]  >>>  [3. SCORE]  >>>  [4. INTEL]  >>>  [5. PROPOSE]  >>>  [6. EXECUTE]  >>>  [7. OVERNIGHT]
    5:45-7 AM          7-8 AM          8-9 AM         continuous        throughout day      market hours         8 PM+
```

| # | Group | What Happens | Key Outputs |
|---|-------|-------------|-------------|
| 1 | **Data Collection** | Finviz screener runs, news ingestion (7 APIs), SEC filings, FRED data | Raw candidates in `trade_ai_scans`, news in `news_articles` |
| 2 | **Enrichment** | 60+ field Finviz enrichment, 17 indicator computations, catalyst classification from 7 sources | Enriched symbols, catalyst scores, indicator cache |
| 3 | **Scoring** | 55-point scoring engine produces GO/WAIT/NO-GO decisions | Scored and classified candidates |
| 4 | **Intelligence** | Multi-strategy classification (24 strategies), LLM analysis, agent routing | Strategy assignments, CIO decisions, agent jobs |
| 5 | **Proposals** | Incubator promotion gates, proposal generation, enrichment packets, LLM 4-chunk review | Paper trade proposals with full research packets |
| 6 | **Execution** | Risk gate validation, bracket order creation, Alpaca paper submission, fill reconciliation, TCA | Paper trades with execution quality metrics |
| 7 | **Overnight** | Portfolio reconciliation, agent scoring, strategy review, embedding refresh, weekly builds | Performance grades, cleaned state, updated indices |

---

## Real-Time Notification Architecture (2026-05-21)

```
Proposal Created (auto_proposal_generator.py)
        |
        v (immediate, daemon thread)
send_telegram_proposal_alert.py --send
        |
        v (< 5 seconds)
Operator sees alert in Telegram with inline buttons
        |
        v (1-2 seconds via long-poll daemon)
Callback detected by run_telegram_callback_poller.py
        |
        v (2-5 seconds)
Action executed: approve → Alpaca order / reject / trail stop / stop out
```

**Latency chain:**

| Stage | Mechanism | Latency |
|-------|-----------|---------|
| Proposal → Alert | Inline hook (daemon thread) | ~5 sec |
| Alert → Operator sees | Telegram push notification | < 1 sec |
| Operator taps button → Detected | Long-poll daemon (25s timeout) | 1-2 sec |
| Action executed | Direct DB + Alpaca API | 2-5 sec |
| **Total end-to-end** | | **~10 seconds** |

**Stop proximity alerts** use the same real-time path. When a trade consumes 50% or 75% of its risk budget, the operator receives inline buttons to stop out, switch to trailing stop, or hold.

**Trailing stop analysis** (`scripts/trailing_stop_analyzer.py`) backfills closed trades with simulated trailing stop outcomes (5/8/10/15% trail vs fixed), determines optimal trail per strategy, and feeds recommendations into `agent_intelligence_rules`. Results visible in Backtesting > Trail Analysis tab.

---

## Data Flow

```
External Sources (12+)
        |
        v
Screener + Ingestion ---- [Group 1]
        |
        v
Enrichment (60+ fields) - [Group 2]
        |
        v
55-Point Scoring --------- [Group 3]
        |
        v
20-Strategy Classifier --- [Group 4]
        |
        v
Incubator Universe
        |
        v
Promotion Gates ---------- [Group 5]
        |
        v
Risk Gate + Paper Execute - [Group 6]
        |
        v
Alpaca Paper Trading API
        |
        v
TCA + Reconciliation ------ [Group 6b]
        |
        v
Overnight Synthesis ------- [Group 7]
```

All state is persisted in PostgreSQL. JSON caches (`data/` directory) serve as fast-read layers for the frontend and agents.

---

## Deployment Model

### Current: Single-Tenant, Single-Server

All 6 services run on one machine. No HA, no auto-scaling. Recovery is manual with documented procedures (see `RESTORE_GUIDE.md`).

**Advantages:** Zero network latency between services, simple operations, low cost.
**Drawbacks:** Single point of failure, no horizontal scaling, GPU contention managed via toll gate.

### Target: Single-Tenant, Cloud-Native

| Component | Cloud Service | Notes |
|-----------|--------------|-------|
| Portfolio Server | Container (ECS Fargate / ACA) | Stateless, auto-scaling |
| PostgreSQL | Managed DB (RDS / Azure PostgreSQL) | Automated backups, HA |
| LLM Inference | GPU instance or managed API | Or route 100% to cloud LLM providers |
| OpenClaw Gateway | Container (ECS Fargate / ACA) | Stateless |
| Cron Scheduler | EventBridge / Logic Apps | Managed, no server |
| React SPA | S3 + CloudFront / Blob + CDN | Static hosting |
| Scalp WebSocket | API Gateway WS / Web PubSub | Managed WebSocket |

**Multi-tenant consideration:** Not currently designed for multi-tenant. Portfolio data, personal situation, and strategy configs are single-user. Multi-tenant would require tenant isolation at DB, config, and agent layers.

---

## External Research Integration

The system ingests from **12+ external sources** across 4 categories:

| Category | Sources | Purpose |
|----------|---------|---------|
| **Market Data** | Finviz Elite, Yahoo Finance, Alpaca, Polygon | Price, volume, screener hits, OHLCV |
| **News & Events** | NewsAPI, Finnhub, FMP, AlphaVantage, RSS | Market-moving events, catalyst verification |
| **Government/Regulatory** | SEC EDGAR, FRED | Insider filings, economic indicators |
| **Qualitative** | YouTube transcripts, social feeds | Earnings language, sentiment |

**Stubs (designed, not live):** Structured earnings transcript provider, alternative data feeds, real-time news WebSocket.

### Topic Intelligence Layer (NEW)

17 DB-driven research topics with closed-loop LLM curation:
- **Ingestion**: YouTube API + Google News RSS + Brave + DuckDuckGo (4-source cascade)
- **Curation**: LLM rates quality (RAG/block), extracts entities (tickers/topics/sectors), links to existing DB records
- **Learning**: Each run generates improved queries based on what was found + personal situation
- **Consumption**: Approved content indexed into RAG, agents receive via entity links + agent events
- **Access**: Command Center `/v2/topic-monitor`, Telegram `topic` commands, API `/api/v2/topics`
- **Daily cost**: Free (YouTube API free tier + Google News RSS + local LLM curation)

---

## LLM Routing

```
Request --> [Toll Gate Lock] --> Local qwen3:14b (GPU)
                                    |
                                    +-- timeout/error --> xAI Grok
                                                            |
                                                            +-- error --> Anthropic Claude
                                                                            |
                                                                            +-- error --> OpenAI
```

Daily budget tracking per provider. Automatic cascade on exhaustion or failure.

### Multi-Tier Trade Review (Separate from Fallback Chain)

Trade reviews use 4 models deliberately for escalating depth — this is not a fallback chain, each tier runs independently on schedule:

| Tier | Model | When | Purpose |
|------|-------|------|---------|
| Realtime | qwen3:14b | Every trade close | Fast 4-agent structured review |
| Overnight | gemma3:27b | 8 PM nightly | Deeper analysis with larger model |
| Weekly | OpenAI gpt-4o | Sunday 10 AM | Cross-trade pattern detection |
| Monthly | Anthropic Claude | 1st of month | Strategic review of all weeklies |

All tiers feed findings back into RAG for future proposal evaluation. Implemented in `multi_tier_trade_reviewer.py`.

---

## Paper Proposal Decision Workflow

```
Incubator → Promoter → Proposal → Enrichment Packet → Operator Review → Approval → Execution
```

Each pending proposal passes through a multi-layer decision packet before the operator can act:

| Layer | What It Proves | Source |
|-------|---------------|--------|
| **Quote Trust** | Is the price from an execution-eligible source (Alpaca/Polygon with bid/ask)? Finviz/yfinance are display-only. | `proposal_quote_trust.py`, `market_quote_provider.py` |
| **Strategy Fit** | Was the strategy selected by evaluating all 20+ YAMLs? Which rules passed/failed? Are there better alternatives? | `multi_setup_router.py`, `strategy_setup_matches` table |
| **Technical Snapshot** | Are RSI, ATR, EMA alignment, VWAP, Fib levels, and ORB status computed? | `proposal_technical_snapshot.py`, `fib_swing_engine.py`, `opening_range_engine.py` |
| **Backtest Evidence** | Is there sufficient historical sample data for this setup type? | `proposal_backtest_engine.py` |
| **AI/Agent Review** | Have LLM and agent reviews been run? | `proposal_agent_review.py`, `proposal_llm_reviewer.py` |
| **Execution Readiness** | Does the proposal pass risk gate, spread check, liquidity check, duplicate check? | `proposal_execution_readiness` table |
| **Approval Gate** | Is the proposal decision-ready? All gates clear? | Phase 6 approval flow |

The operator sees a **Trust Audit** panel per proposal showing quote trust status, strategy fit score with all evaluations, technical/backtest evidence, and structured approval blockers.

**Approval is blocked** when: execution readiness not checked, quote is display-only/stale, RSI blocks, or proposal exceeds staleness policy.

---

## Governance & Maturity

| System | Schedule | Purpose |
|--------|----------|---------|
| **GOV-1** System Facts + A1A | 07:40-07:50 M-F, 18:00-18:10 Sun | Automated documentation compliance |
| **Phase 9C** Maturity Board | 07:55-08:00 M-F, 18:15-18:20 Sun | Consolidated maturity score + operator readiness |
| **SP-1** Strategy Proof | On-demand | Evidence funnel, proof status per strategy |
| **A-5 Observation** | Ends 2026-05-22 | 5-business-day validation window |

Current maturity: **7.1/10**. Live trading: **BLOCKED**.

---

## Key Metrics

| Metric | Current Value |
|--------|--------------|
| Portfolio value | ~$1.19M |
| Positions | ~50 |
| Enriched symbols | 1,139 |
| News articles ingested | 2,787 |
| CIO decisions tracked | 55 |
| Agent handoffs | 110 (32 escalations) |
| Active incubator symbols | ~55 |
| Paper trades | 4 open, 0 closed |
