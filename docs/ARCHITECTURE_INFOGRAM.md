# Trade AI v12 -- Architecture Infogram

**Last updated:** 2026-05-09

---

## A) System-at-a-Glance

```
+========================================================================+
||                     TRADE AI v12  --  ms01-openclaw                   ||
+========================================================================+
|                                                                        |
|  Portfolio ........... ~$1.19M (taxable + IRA, ~50 positions)          |
|  Mode ................ PAPER ONLY (live trading locked)                 |
|  Database ............ 299 tables, PostgreSQL 15                       |
|  Strategies .......... 20 (dynamic YAML, multi-assignment)             |
|  Pipeline ............ 31 stages, 7 groups                             |
|  Screeners ........... 2 active (Finviz Elite, 4 run windows)          |
|  API ................. 80+ endpoints (Flask :7777)                      |
|  Agents .............. 4 conversational + 3 backend                     |
|  LLM ................. qwen3:14b local (GPU) + 3 cloud fallbacks       |
|  Frontend ............ 55 pages (React SPA, Command Center v2)         |
|  Cron ................ 142 scheduled jobs                               |
|  External Sources .... 12+ (market, news, regulatory, qualitative)     |
|                                                                        |
+========================================================================+
```

---

## B) Orchestration Chevrons

### The 7 Pipeline Groups (Daily Flow)

```
  +------------------+     +---------------+     +-------------+     +----------------+     +--------------+     +--------------+     +---------------+
  |  1. DATA         | >>> |  2. ENRICH    | >>> |  3. SCORE   | >>> |  4. INTEL      | >>> |  5. PROPOSE  | >>> |  6. EXECUTE  | >>> |  7. OVERNIGHT |
  |  COLLECTION      |     |               |     |             |     |                |     |              |     |              |     |               |
  |  5:45-7:00 AM    |     |  7:00-8:00 AM |     |  8:00-9 AM  |     |  continuous    |     |  throughout  |     |  market hrs  |     |  8 PM+        |
  |                  |     |               |     |             |     |                |     |              |     |              |     |               |
  |  Finviz screener |     |  60+ fields   |     |  55-point   |     |  20-strategy   |     |  Incubator   |     |  Risk gate   |     |  Overnight    |
  |  News (7 APIs)   |     |  17 indicators|     |  scoring    |     |  classifier    |     |  promotion   |     |  Paper order |     |  Agent scores |
  |  SEC filings     |     |  7 catalyst   |     |  GO/WAIT/   |     |  LLM analysis  |     |  Enrichment  |     |  Alpaca fill |     |  Weekly build |
  |  FRED econ data  |     |  sources      |     |  NO-GO      |     |  CIO decisions |     |  LLM review  |     |  TCA + recon |     |  Cleanup      |
  +------------------+     +---------------+     +-------------+     +----------------+     +--------------+     +--------------+     +---------------+
```

### Inputs and Outputs Per Group

```
 [EXTERNAL SOURCES]                                                                                    [OPERATOR]
  Finviz Elite    ---+                                                                                     |
  NewsAPI         ---+                                                                                     |
  Finnhub         ---+---> [ GROUP 1 ] ---> raw scans + news + filings                                     |
  SEC EDGAR       ---+          |                                                                          |
  FRED            ---+          v                                                                          |
  Yahoo Finance   ---+     [ GROUP 2 ] ---> enriched symbols (60+ fields) + indicator cache                |
                                |                                                                          |
                                v                                                                          |
                           [ GROUP 3 ] ---> scored candidates (55 pts) + GO/WAIT/NO-GO                     |
                                |                                                                          |
                                v                                                                          |
                           [ GROUP 4 ] ---> strategy assignments + CIO decisions + agent jobs               |
                                |                                                                          |
                                v                                                                          |
                           [ GROUP 5 ] ---> paper_trade_proposals (with enrichment packets)                 |
                                |                                                                          |
                                v                                               +--------+                 |
                           [ GROUP 6 ] ---> paper trades on Alpaca -----------> | REVIEW | <---------------+
                                |                                               | APPROVE|   (human-in-loop)
                                v                                               +--------+
                           [ GROUP 7 ] ---> performance grades + cleaned state + reports
                                |
                                v
                          [NEXT DAY GROUP 1]
```

---

## C) Component Interaction Map

```
  +-------+                                  +--------------------+
  | USER  |                                  |  TELEGRAM / WHATSAPP|
  | (John)|                                  +--------+-----------+
  +---+---+                                           |
      |                                               v
      |  browser                              +-------+--------+
      +-------------------------------------->| OPENCLAW GW    |
      |                                       | :18789         |
      v                                       | Maria  Steph   |
  +--------+                                  | Aegis  Alex    |
  | REACT  |                                  +-------+--------+
  | SPA    |                                          |
  | /v2/   |                                          |
  +---+----+                                          |
      |                                               |
      v                                               v
  +---+--------------------------------------------+----+
  |              PORTFOLIO SERVER (:7777)                 |
  |              80+ API endpoints                       |
  |              Flask + static file serving              |
  +---+----------------+----------------+--------+------+
      |                |                |        |
      v                v                v        v
  +---+---+     +------+------+  +-----+-----+  +-----+--------+
  | PG 15 |     | OLLAMA LLM  |  | EXTERNAL  |  | CLOUD LLM    |
  | :5432 |     | :11434      |  | APIs      |  | FALLBACK     |
  | 219   |     | qwen3:14b   |  | 12+       |  | xAI > Claude |
  | tables|     | Intel Arc   |  | sources   |  | > OpenAI     |
  +-------+     | B50 GPU     |  +-----------+  +--------------+
                +-------------+

  +-----------------------------------------------------------+
  |                    CRON SCHEDULER                          |
  |  142 jobs --> triggers scripts --> writes to PG/files      |
  +-----------------------------------------------------------+

  +-----------------------------------------------------------+
  |                  BACKEND AGENTS                            |
  |  Iris (hygiene) | Watchdog (health) | Scalp Critic (LLM)  |
  +-----------------------------------------------------------+
```

---

## D) Detailed Inputs/Outputs Table

| Stage | Inputs | Processing | Outputs | Storage |
|-------|--------|-----------|---------|---------|
| **Finviz Screener** | Finviz Elite API (cookie + token) | CSV download + parse, 4 windows/day | Screener hits | `trade_ai_scans` (PG) |
| **News Ingestion** | NewsAPI, Finnhub, FMP, Polygon, RSS | Multi-source fetch + dedup | Articles + entities | `news_articles`, `intelligence_entities` (PG) |
| **SEC Ingestion** | SEC EDGAR API | Form 4 insider filing parse | Insider activity | `sec_form4` (PG) |
| **FRED Ingestion** | FRED API | Economic indicator pull | Macro data | `fundamental_data` (PG) |
| **Finviz Enrichment** | Finviz 5-view pages | 60+ field extraction per symbol | Enriched profiles | `ticker_enrichment_cache` (JSON + PG) |
| **Catalyst Enrichment** | 7 API sources | Article fetch + classify + verify | Catalyst scores | `catalyst_cache` (PG) |
| **Indicator Engine** | yfinance OHLCV data | 17 technical indicator computation | Confluence scores | `indicator_confluence_cache` (PG) |
| **Scoring Engine** | Scans + enrichment + indicators | 55-point weighted scoring | GO/WAIT/NO-GO | `trade_ai_scans.score` (PG) |
| **Strategy Classifier** | Scored symbols + enrichment | 20 YAML filter + LLM classification | Strategy assignments | `incubator_universe` (PG) |
| **Proposal Promoter** | ACTIVE incubator symbols | Score/catalyst gates | Trade proposals | `paper_trade_proposals` (PG) |
| **LLM Reviewer** | Proposal data | 4-chunk review pipeline | Quality assessment | `paper_trade_proposals.llm_review_*` (PG) |
| **Risk Gate** | Proposal + portfolio state | Exposure/correlation/size checks | Pass/fail | `paper_trade_proposals.risk_*` (PG) |
| **Paper Execution** | Approved proposal | Bracket order creation | Alpaca paper trade | `paper_trades` (PG) |
| **Reconciliation** | Fills vs expectations | Slippage/timing analysis | Recon items | `broker_reconciliation_items` (PG) |
| **TCA** | Fill data + market data | Execution quality metrics | Performance grades | `paper_execution_quality` (PG) |
| **Overnight Batch** | Daily accumulated data | Consolidation + metrics | System metrics | `daily_system_metrics` (PG) |
| **Agent Jobs** | Watchlist symbols | LLM-driven analysis | Research results | `watchlist_agent_results` (PG) |

---

## E) Service-to-Service Call Map

```
Caller                     -->  Target                      -->  Purpose
--------------------------     -------------------------       ---------------------------
Cron                       -->  Python scripts              -->  Pipeline stage execution
Python scripts             -->  PostgreSQL (:5432)          -->  State read/write
Python scripts             -->  Ollama (:11434)             -->  LLM inference
Python scripts             -->  External APIs               -->  Data ingestion
Python scripts             -->  Portfolio Server (:7777)    -->  Internal API calls
Portfolio Server           -->  PostgreSQL (:5432)          -->  Query handling
Portfolio Server           -->  Ollama (:11434)             -->  On-demand inference
Portfolio Server           -->  Static files                -->  React SPA serving
React SPA (browser)        -->  Portfolio Server (:7777)    -->  API consumption
OpenClaw Gateway           -->  Ollama (:11434)             -->  Agent LLM responses
OpenClaw Gateway           -->  PostgreSQL (:5432)          -->  Agent data queries
OpenClaw Gateway           -->  Portfolio Server (:7777)    -->  Portfolio/strategy data
Telegram/WhatsApp          -->  OpenClaw Gateway (:18789)   -->  User messages
Pipeline Watchdog          -->  Telegram Bot API            -->  Failure alerts
Alerting system            -->  Telegram / WhatsApp / Email -->  Notifications
```

---

## F) People and Actors

### Operator

| Actor | Role | Interfaces | Responsibilities |
|-------|------|-----------|-----------------|
| **John (Owner/Operator)** | Reviews proposals, approves/rejects paper trades, monitors pipeline health, manages `.env` config, validates strategy performance | Command Center UI, Telegram, Terminal | Final approval authority. Human-in-the-loop gate. |

### Conversational Agents (OpenClaw Gateway :18789)

| Agent | Specialty | Accessible Via | Key Outputs |
|-------|-----------|---------------|-------------|
| **Maria** | Risk analysis, position sizing, portfolio exposure | Telegram, WhatsApp | Risk assessments, sizing recommendations |
| **Steph** | Technical analysis, chart patterns, indicator confluence | Telegram, WhatsApp | Entry/exit zones, pattern analysis |
| **Aegis** | Synthesis, morning briefs, cross-agent coordination | Telegram, WhatsApp | Daily briefs, overnight summaries |
| **Alex** | Income strategies, dividends, Roth conversion, SSDI/IRMAA | Telegram, WhatsApp | Tax-aware income analysis |

### Backend Agents (Automated)

| Agent | Role | Trigger | Output |
|-------|------|---------|--------|
| **Iris** | Library hygiene -- content quality, stale data detection | Cron (daily alerts) | Telegram alerts for 0-article topics |
| **Pipeline Watchdog** | Health monitoring -- 31 stage failure/delay detection | Continuous | Failure/staleness alerts |
| **Scalp Critic** | LLM critique of screener candidates before promotion | Pre-promotion trigger | Quality gate pass/fail |

### External Services (No Human Actor)

| Category | Services | Authentication |
|----------|----------|---------------|
| **Market Data** | Finviz Elite, Alpaca (paper), Polygon, Yahoo Finance | Cookie+Token, API key, API key, None |
| **News/Fundamentals** | Finnhub, NewsAPI, FMP, AlphaVantage | API key (x4) |
| **Government** | SEC EDGAR, FRED | Public, API key |
| **LLM (local)** | Ollama (qwen3:14b, Intel Arc B50 Vulkan) | None (localhost) |
| **LLM (cloud)** | xAI Grok, Anthropic Claude, OpenAI | API key (x3) |
| **Messaging** | Telegram Bot, Twilio (WhatsApp), SMTP | Bot token, Twilio creds, SMTP creds |

---

## G) Architecture Decision Records

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| Single-server deployment | Simplicity, zero network latency, low cost | No HA, single point of failure |
| Local LLM primary | Privacy, no per-call cost, GPU-accelerated | Limited model size (14B), Intel Arc constraints |
| 4-provider LLM cascade | Resilience against any single provider outage | Complexity in routing logic |
| YAML-driven strategies | Non-code strategy changes, rapid iteration | Must validate YAML structure |
| Cron-based orchestration | Simple, proven, easy to debug | No DAG dependencies, manual ordering |
| Paper-only mode (6 months) | Validate system before risking capital | Extended timeline before live |
| PostgreSQL for everything | Single data store, simple backup/restore | No time-series optimization, no search index |
| JSON file caches | Fast frontend reads, reduce DB load | Dual-write risk, cache staleness |
| Human-in-the-loop proposals | Prevent automated losses | Bottleneck on operator availability |
