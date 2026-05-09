# Trade AI v12 -- Architecture Overview

**Audience:** Executive / architect level
**Last updated:** 2026-05-09

---

## What Is Trade AI v12?

Trade AI v12 is an automated trading intelligence platform that discovers, evaluates, and paper-trades equity setups against a ~$1.19M multi-account portfolio. It combines quantitative screening, 20 configurable strategies, LLM-powered analysis, and 4 conversational AI agents into a single-tenant cloud-deployable service.

**Current state:** Self-hosted on a dedicated Linux server (`ms01-openclaw`). All services co-located. Paper trading only -- live trading locked behind a 6-month validation gate.

---

## High-Level Architecture

```
+-----------------------------------------------------------------------------------+
|                               ms01-openclaw (Linux)                                |
|                                                                                    |
|   +-----------+     +-------------+     +------------+     +------------------+    |
|   | React SPA | --> | Portfolio    | --> | PostgreSQL | <-- | Cron Scheduler   |    |
|   | (55 pgs)  |     | Server :7777|     | :5432      |     | (141 jobs)       |    |
|   +-----------+     | 80+ APIs    |     | 256 tables |     +------------------+    |
|                     +------+------+     +------------+                              |
|                            |                                                       |
|              +-------------+-------------+                                         |
|              |                           |                                         |
|   +----------v----------+     +----------v----------+                              |
|   | Ollama LLM :11434   |     | OpenClaw GW :18789  |                              |
|   | qwen3:14b           |     | 4 Agents            |                              |
|   | Intel Arc B50 GPU   |     | (Maria/Steph/Aegis/ |                              |
|   +---------------------+     |  Alex)              |                              |
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
| **Portfolio Server** (:7777) | Central API hub. Serves 80+ REST endpoints and the React SPA. All client-facing traffic routes through here. | 11,700 LOC handler |
| **PostgreSQL** (:5432) | Single source of truth. All persistent state -- trades, proposals, enrichment, agent results, pipeline health. | 256 tables |
| **Ollama LLM** (:11434) | Local inference engine. Strategy classification, proposal review, health checks. GPU-accelerated on Intel Arc B50 (Vulkan). | ~15s/chunk, toll-gated |
| **OpenClaw Gateway** (:18789) | Conversational AI routing. 4 agents accessible via Telegram + WhatsApp. Handles natural language queries about portfolio, risk, and strategy. | 4 agents |
| **Cron Scheduler** | Orchestrates the 31-stage pipeline across 7 groups. 141 scheduled jobs from 4 AM to midnight. | 141 crontab entries |
| **React SPA** | Operator dashboard. 55 pages covering portfolio, watchlist, proposals, strategy admin, risk, journal, governance. | 91 React components |

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
| 4 | **Intelligence** | Multi-strategy classification (20 strategies), LLM analysis, agent routing | Strategy assignments, CIO decisions, agent jobs |
| 5 | **Proposals** | Incubator promotion gates, proposal generation, enrichment packets, LLM 4-chunk review | Paper trade proposals with full research packets |
| 6 | **Execution** | Risk gate validation, bracket order creation, Alpaca paper submission, fill reconciliation, TCA | Paper trades with execution quality metrics |
| 7 | **Overnight** | Portfolio reconciliation, agent scoring, strategy review, embedding refresh, weekly builds | Performance grades, cleaned state, updated indices |

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
