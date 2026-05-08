# Trade AI v12 -- Architecture Infogram

---

## A) System-at-a-Glance

```
+--------------------------------------------------------------+
|                    TRADE AI v12  --  ms01-openclaw             |
+--------------------------------------------------------------+
|                                                              |
|  Portfolio .... ~$1.19M     Paper Mode     33 positions      |
|  Database ..... 219 tables  PostgreSQL 15                    |
|  Strategies ... 20          dynamic from YAML                |
|  Pipeline ..... 31 stages   7 groups                         |
|  Screeners .... 2 active    Finviz Elite                     |
|  API .......... 80+ endpoints                                |
|  Agents ....... 4 conversational + 3 backend                 |
|  LLM .......... qwen3:14b (local) + 4 cloud providers       |
|  Frontend ..... 50+ pages   React SPA                        |
|  Cron ......... 130 scheduled jobs                           |
|                                                              |
+--------------------------------------------------------------+
```

---

## B) Orchestration Chevrons

> Full Mermaid source: `docs/diagrams/orchestration_chevrons.mmd`

### The 7 Pipeline Groups

```
  [1. DATA COLLECTION]  >>>  [2. ENRICHMENT]  >>>  [3. SCORING]  >>>  [4. INTELLIGENCE]  >>>  [5. PROPOSALS]  >>>  [6. EXECUTION]  >>>  [7. OVERNIGHT]
```

#### Group Details

| Group | Key Stages | Schedule |
|-------|-----------|----------|
| **1. Data Collection** | Finviz screener download, news ingestion (7 APIs), market data fetch | 5:45--7:00 AM |
| **2. Enrichment** | Finviz 5-view enrichment (60+ fields), indicator engine (17 indicators), catalyst classification | 7:00--8:00 AM |
| **3. Scoring** | 55-point scoring engine, GO/WAIT/NO GO decision output | 8:00--8:15 AM |
| **4. Intelligence** | Multi-strategy classifier (20 strategies), LLM analysis, incubator refresh | 8:15--8:30 AM |
| **5. Proposals** | Incubator promotion gates (score + catalyst), proposal generation, risk checks | 8:30--9:00 AM |
| **6. Execution** | Spread/price/risk validation, bracket order creation, Alpaca paper submission | Orchestrator runs: 04:00, 07:00, 09:00, 10:00 |
| **7. Overnight** | Portfolio reconciliation, weekly incubator build, cleanup, DB maintenance | 8:00 PM+, Sunday PM |

---

## C) Component Interaction Map

> Full Mermaid source: `docs/diagrams/system_interaction_map.mmd`

```
                                   +-------------+
                                   |  Telegram /  |
                                   |  WhatsApp    |
                                   +------+------+
                                          |
                                          v
+--------+     +----------+     +---------+--------+     +-----------+
|  User   | --> | Browser  | --> | Portfolio Server | --> | PostgreSQL|
| (John)  |     | React SPA|     |    :7777         |     |   :5432   |
+--------+     +----------+     +--------+---------+     +-----------+
                                         |
                          +--------------++--------------+
                          |               |              |
                          v               v              v
                   +------+------+ +------+------+ +-----+--------+
                   | Ollama LLM  | | OpenClaw GW | | External APIs|
                   | :11434      | | :18789      | | Finviz, etc. |
                   | qwen3:14b   | | 4 agents    | |              |
                   +-------------+ +------+------+ +--------------+
                                          |
                                   +------+------+
                                   | Cloud LLM   |
                                   | Fallback     |
                                   | grok/claude/ |
                                   | openai       |
                                   +-------------+
```

---

## D) Inputs/Outputs Table

| Stage | Inputs | Processing | Outputs |
|-------|--------|-----------|---------|
| **Finviz Screener** | Finviz Elite API | CSV download + parse | `trade_ai_scans` rows |
| **Enrichment** | Finviz API (5 views) | 60+ field extraction | `ticker_enrichment_cache.json` |
| **Catalyst** | 7 news APIs | Article fetch + classify | `catalyst_verified`, `news_articles` |
| **Scoring** | Scans + enrichment | 55-point scoring engine | GO/WAIT/NO GO decisions |
| **Indicator Engine** | yfinance OHLCV | 17 technical indicators | `indicator_confluence_cache` |
| **Strategy Classifier** | Scans + enrichment + indicators | 20 strategy filters + LLM | `incubator_universe` rows |
| **Proposal Promoter** | Incubator ACTIVE | Score/catalyst gates | `paper_trade_proposals` |
| **Execution Check** | Market quotes (Alpaca/Polygon) | Spread/price/risk validation | `readiness_state` |
| **Paper Submit** | Proposal + readiness | Bracket order creation | Alpaca paper trade |

---

## E) People and Actors

### Operator

| Actor | Role | Interface |
|-------|------|-----------|
| **John (Operator)** | Reviews proposals, approves/rejects paper trades, monitors pipeline health, manages `.env` config | Command Center UI (React SPA) |

### Conversational Agents (OpenClaw Gateway :18789)

| Agent | Specialty | Channels |
|-------|-----------|----------|
| **Maria** | Risk analysis, position sizing, portfolio exposure | Telegram, WhatsApp |
| **Steph** | Technical analysis, chart patterns, indicator confluence | Telegram, WhatsApp |
| **Aegis** | Synthesis, morning briefs, cross-agent coordination | Telegram, WhatsApp |
| **Alex** | Income strategies, dividends, covered calls (RAG-enabled) | Telegram, WhatsApp |

### Backend Agents

| Agent | Role |
|-------|------|
| **Iris** | Library hygiene -- dependency audits, version tracking |
| **Pipeline Watchdog** | Health monitoring -- stage failures, stale data alerts |
| **Scalp Critic** | LLM critique -- reviews proposals for quality before promotion |

### External Services

| Category | Services |
|----------|----------|
| **Market Data** | Finviz Elite, Alpaca (paper), Polygon, Yahoo Finance |
| **News/Fundamentals** | Finnhub, NewsAPI, FMP (Financial Modeling Prep), AlphaVantage |
| **LLM (local)** | Ollama -- qwen3:14b on Intel Arc B50 (Vulkan) |
| **LLM (cloud)** | Anthropic (Claude), OpenAI, xAI (Grok) |
