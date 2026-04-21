# OpenClaw Portfolio Advisor-Agent — Planning Brief

**Version:** 1.0  
**Date:** 2026-04-20  
**Author:** Claude Opus 4.6 (architect pass)  
**Status:** PLANNING — not yet approved for implementation  
**Host:** ms01-openclaw (Ubuntu 25.10, 64GB RAM, Intel Arc GPU, PostgreSQL 17.9)

---

## 1. Executive Summary

### What this is

OpenClaw is a **persistent, proactive portfolio advisor-agent** that runs continuously on ms01-openclaw, monitors John's $1.2M multi-account portfolio, and escalates findings via structured notifications when action may be warranted.

### How it differs from current systems

| Current System | OpenClaw Advisor |
|----------------|-----------------|
| **Trade AI** — scalp screener, runs on schedule, produces dashboards | Consumes Trade AI output as one of many inputs |
| **Portfolio Intelligence** — daily pipeline, generates reports and AI analysis | Consumes PI output; adds temporal reasoning, comparison, and proactive surveillance |
| **Reports (DOCX, HTML)** — static artifacts for human review | Dynamic advisor that decides what's important enough to surface |
| **Caches and state files** — overwritten each run, no continuity | Persistent memory that tracks what it recommended, why, and what happened |

### Why this is the right next step

The infrastructure is ready:
- 9 Postgres tables accumulating daily history (snapshots, signals, performance, state, briefs)
- Freshness manifest with holdings_hash for detecting composition changes
- Cache invalidation triggered by portfolio and personal changes
- Dual-write pattern proven across 8 flows
- Ollama local LLM operational (qwen3:1.7b for fast inference)
- All existing data sources (Finviz, Yahoo, Finnhub, NewsAPI, Polygon, FMP, Brave) already wired

The gap: no agent currently connects these dots across time, compares against alternatives, or escalates proactively. That's what OpenClaw becomes.

---

## 2. Mission Profile

### Primary missions

| Mission | Description | Cadence |
|---------|-------------|---------|
| **Portfolio surveillance** | Monitor all positions for regime changes, stop proximity, earnings impact, concentration drift | Continuous (every pipeline run) |
| **Dividend/compounding watch** | Track yield quality, dividend cuts/raises, ex-div opportunities, income trajectory vs target | Daily + event-triggered |
| **Rotation evaluation** | Compare current holdings against better alternatives (growth, quality, yield, defense) | Weekly + on significant events |
| **Risk regime awareness** | Detect market-wide shifts (VIX regime, sector rotation, macro events) that change portfolio thesis validity | Daily + breaking-news triggered |
| **Forecast continuity** | Maintain 1Y/2Y/3Y/5Y outlook per position and total portfolio. Compare forecasts to actuals. | Monthly synthesis, quarterly review |
| **Recommendation memory** | Track what was recommended, when, why, and whether it proved correct | Always-on (every recommendation stored) |

### Operating philosophy

- **Proactive, not reactive** — the agent decides what matters, not the user
- **Opinion with provenance** — every recommendation cites data, model, confidence, and timestamp
- **Cost-aware** — defaults to free/local analysis; escalates to paid APIs only when the finding justifies it
- **Self-auditing** — tracks its own accuracy and adjusts confidence over time

---

## 3. Operating Model

### Tier 1: Local Ollama (always-on, free)

| Capability | Model | Use Case |
|------------|-------|----------|
| Broad monitoring & scoring | qwen3:1.7b | Signal classification, relevance scoring, routine screening |
| News/article scoring | qwen3:1.7b | "Is this article relevant to portfolio?" filtering |
| Sentiment classification | qwen3:1.7b | Bull/bear/neutral from social/news text |
| Summary generation | qwen3:1.7b or 8b | Quick position summaries, daily digest prep |
| Pattern detection | qwen3:1.7b | "Is this signal recurring?" type questions |

**Constraints:** No external API cost. Can run every 15-30 minutes during market hours. Handles 90%+ of daily monitoring volume.

### Tier 2: External Escalation (on-demand, paid)

| Capability | Model | Trigger |
|------------|-------|---------|
| Deep thesis validation | Claude Sonnet 4 | Position risk change, concentration threshold, rotation candidate |
| Comparative analysis | GPT-4o | "Is X better than Y for this allocation?" |
| Forecast synthesis | Claude Opus | Monthly/quarterly outlook generation |
| Recommendation framing | Claude Sonnet | Final advisory wording before user notification |

**Cost model:** ~$0.02-0.10 per escalation. Budget: $5-15/month typical, $30 max on high-activity months.

### Escalation thresholds

| Metric | Local Threshold | Escalate When |
|--------|----------------|---------------|
| Position size change | Track all | Position crosses 10% or 15% of portfolio |
| Dividend yield change | Track all | Yield drops >15% from prior quarter OR cut announced |
| Analyst consensus shift | Track all | Average target changes >10% OR 2+ downgrades same week |
| Signal persistence | Track all | Ticker at TRIM for 5+ consecutive days without action |
| Market regime | Daily VIX/breadth | VIX >30 sustained OR sector rotation contradicts thesis |
| Opportunity score | Score locally | Local score >0.7 AND involves >$10K allocation decision |
| Social spike | Count locally | Unusual volume (>3x baseline) on portfolio holdings |

### Human-in-the-loop checkpoints

| Action | Requires Human? | Notes |
|--------|:-:|-------|
| Write observation to memory | No | Agent auto-records |
| Update opportunity queue | No | Agent auto-records |
| Generate recommendation | No | Agent generates |
| Send email alert | **Yes (initially)** | First 30 days: all emails require queue → user reviews daily. After validation period: urgent alerts auto-send, digests auto-send. |
| Execute trade | **Always** | Agent NEVER trades. Only recommends. |
| Modify stop levels | **Yes** | Agent proposes, user confirms via modal |
| Change thesis config | **Yes** | Agent proposes, architect approves |

### Auto-write vs recommendation-only

| Category | Auto-write OK | Recommendation only |
|----------|:---:|:---:|
| Observation (what happened) | ✓ | |
| Classification (bull/bear/neutral) | ✓ | |
| Score/confidence | ✓ | |
| Recommendation (buy/sell/trim/rotate) | | ✓ |
| Forecast (price target, yield projection) | ✓ (marked speculative) | |
| Email to user | | ✓ (after validation period: auto for digests) |

---

## 4. Data Sources the Agent Should Consume

### Current sources (already available)

| Source | Location | Cadence | Trust | Storage Direction |
|--------|----------|---------|-------|-------------------|
| Holdings (positions, values, accounts) | `holdings.json` + `holdings` table | Every 30min (market hrs) | HIGH | Already dual-write |
| Action signals per ticker | `action_signals.json` + `action_signals_history` | Daily | HIGH | Already dual-write |
| Performance returns (period) | `performance_history.json` + `performance_daily` | Daily | HIGH | Already dual-write |
| Portfolio snapshots (total value) | `snapshots/*.json` + `portfolio_snapshots` | Daily | HIGH | Already dual-write |
| Price history (OHLCV) | `price_cache.json` + `price_cache` | Weekly (Yahoo) | HIGH | Already dual-write |
| Trade AI state (per-ticker) | `data/state.json` + `trade_ai_state` | Daily + live cycles | MEDIUM | Already dual-write |
| Run summaries | `run_summary.json` + `run_summary` | Per Trade AI run | MEDIUM | Already dual-write |
| Intel briefs (generation log) | `intel_briefs` table | Daily | HIGH | Postgres-only metadata |
| Personal situation | `personal_situation.json` + `personal_history` | On modal edit | HIGH | Already dual-write |
| Dividend calendar | `dividend_calendar.json` | Daily | HIGH | JSON → **migrate to DB** |
| Finviz quote cache (live prices) | `finviz_quote_cache.json` | Every 30min | HIGH | Stay JSON (live cache) |
| Ticker enrichment (Finviz full) | `ticker_enrichment_cache.json` | 6-hr TTL | HIGH | Stay JSON (cache) |
| Portfolio news + catalysts | `portfolio_news.json` + history/ | Daily | MEDIUM | JSON + 90-day rolling files |
| Technical snapshot | `technical_snapshot.json` | Daily | MEDIUM | Stay JSON (current-state) |
| Risk management / stops | `risk_management.json` + `stops.json` | Daily + manual | HIGH | Stay JSON (operational) |
| Retirement roadmap | `retirement_roadmap.json` | Daily | HIGH | Stay JSON (computed) |
| AI analysis cache (sections) | `ai_*.json` (7 files) | Monthly/daily | MEDIUM | Stay JSON (TTL cache) |
| Monthly advisory | `monthly_advisory.json` | Monthly | HIGH | JSON → **merge into intel_briefs** |
| Stress test results | `stress_test.json` | Daily | MEDIUM | Stay JSON |

### New sources the agent should ingest (not yet built)

| Source | Purpose | Cadence | Implementation |
|--------|---------|---------|----------------|
| Yahoo Finance fundamentals | P/E, revenue growth, margins, guidance | Weekly | yfinance API, store in new `fundamentals` table |
| Analyst ratings/targets | Consensus PT, upgrades/downgrades | Daily | Finviz + Yahoo, store in `analyst_consensus` table |
| Reddit/StockTwits sentiment | Social pulse on held tickers | Daily during market | API scrape, score locally, store in `social_sentiment_history` |
| Broker transaction data | Actual buys/sells (Phase 11C) | On import | CSV → `transactions` table (Tier 4) |
| Macro indicators | Fed rate, inflation, GDP, unemployment | Weekly | FRED API or manual, store in `macro_indicators` |

---

## 5. Advisor-Memory / Database Strategy

### Core principle

The agent's memory IS its Postgres database. Every observation, recommendation, and outcome is stored with timestamp, model provenance, and confidence level.

### Proposed new tables for advisor memory

#### `advisor_observations`
What the agent noticed.

```sql
CREATE TABLE advisor_observations (
    id serial PRIMARY KEY,
    observed_at timestamptz DEFAULT now(),
    symbol varchar(20),                    -- NULL for portfolio-level observations
    category varchar(30) NOT NULL,         -- 'dividend'|'risk'|'opportunity'|'regime'|'thesis'|'social'
    observation text NOT NULL,             -- natural language finding
    evidence jsonb,                        -- supporting data points
    model varchar(30) NOT NULL,            -- 'ollama:qwen3:1.7b'|'claude-sonnet-4'|'gpt-4o'
    confidence numeric(3,2),              -- 0.00 to 1.00
    escalation_tier smallint DEFAULT 1,   -- 1=local, 2=external
    expires_at date,                      -- when this observation becomes stale
    superseded_by integer REFERENCES advisor_observations(id)
);
```

#### `advisor_recommendations`
What the agent recommends.

```sql
CREATE TABLE advisor_recommendations (
    id serial PRIMARY KEY,
    created_at timestamptz DEFAULT now(),
    symbol varchar(20),
    action varchar(20) NOT NULL,          -- 'BUY'|'SELL'|'TRIM'|'ROTATE'|'HOLD'|'WATCH'|'ADD'
    rationale text NOT NULL,
    target_allocation_pct numeric(5,2),
    confidence numeric(3,2),
    model varchar(30) NOT NULL,
    observations integer[],               -- FK array to supporting observations
    status varchar(20) DEFAULT 'pending', -- 'pending'|'accepted'|'rejected'|'expired'|'superseded'
    actioned_at timestamptz,
    outcome_notes text,
    outcome_pnl numeric(12,2)
);
```

#### `advisor_forecasts`
Multi-horizon outlook per position and portfolio.

```sql
CREATE TABLE advisor_forecasts (
    id serial PRIMARY KEY,
    forecast_date date NOT NULL,
    symbol varchar(20),                   -- NULL for portfolio total
    horizon varchar(5) NOT NULL,          -- '1Y'|'2Y'|'3Y'|'5Y'
    forecast_value numeric(14,2),         -- projected price or portfolio value
    forecast_yield numeric(6,3),          -- projected dividend yield
    confidence numeric(3,2),
    model varchar(30),
    assumptions jsonb,                    -- key assumptions (growth rate, payout ratio, etc.)
    actual_value numeric(14,2),           -- filled in when horizon expires
    accuracy_pct numeric(6,2),            -- calculated post-hoc
    UNIQUE(forecast_date, symbol, horizon)
);
```

#### `article_index`
Metadata for all articles/news consumed.

```sql
CREATE TABLE article_index (
    id serial PRIMARY KEY,
    published_at timestamptz,
    ingested_at timestamptz DEFAULT now(),
    title text NOT NULL,
    url text UNIQUE,
    source varchar(50),                   -- 'finnhub'|'newsapi'|'yahoo'|'brave'|'reddit'|'stocktwits'
    symbols varchar(20)[],               -- tickers mentioned
    relevance_score numeric(3,2),        -- 0-1 agent-assigned
    sentiment varchar(10),               -- 'bullish'|'bearish'|'neutral'
    catalyst_type varchar(30),           -- 'earnings'|'dividend'|'analyst'|'macro'|'insider'
    summary text,                         -- agent-generated summary
    model varchar(30)
);
```

#### `analyst_consensus_history`
Track analyst target/rating changes over time.

```sql
CREATE TABLE analyst_consensus_history (
    id serial PRIMARY KEY,
    snapshot_date date NOT NULL,
    symbol varchar(20) NOT NULL,
    mean_target numeric(10,2),
    median_target numeric(10,2),
    high_target numeric(10,2),
    low_target numeric(10,2),
    buy_count integer,
    hold_count integer,
    sell_count integer,
    upgrades_30d integer,
    downgrades_30d integer,
    data jsonb,
    UNIQUE(snapshot_date, symbol)
);
```

#### `dividend_history`
Historical yield and dividend data per ticker.

```sql
CREATE TABLE dividend_history (
    id serial PRIMARY KEY,
    record_date date NOT NULL,
    symbol varchar(20) NOT NULL,
    annual_yield numeric(6,3),
    quarterly_amount numeric(10,4),
    ex_div_date date,
    pay_date date,
    growth_yoy_pct numeric(6,2),
    payout_ratio numeric(6,2),
    data jsonb,
    UNIQUE(record_date, symbol)
);
```

#### `notification_log`
Audit trail for all emails/alerts sent.

```sql
CREATE TABLE notification_log (
    id serial PRIMARY KEY,
    sent_at timestamptz DEFAULT now(),
    channel varchar(20) NOT NULL,        -- 'gmail'|'telegram'|'dashboard'
    notification_type varchar(30),        -- 'urgent_alert'|'daily_digest'|'weekly_synthesis'|'opportunity'
    subject text,
    body_preview text,
    recommendation_ids integer[],         -- FKs to advisor_recommendations
    delivered boolean DEFAULT true
);
```

### What stays JSON-first

| Data | Reason |
|------|--------|
| Finviz caches | Live operational caches with short TTL |
| AI section caches | Volatile with TTL-based invalidation |
| Risk management | Current-state operational file |
| Technical snapshot | Current-state, rebuilt each run |
| Config files (stops, watchlist, screeners) | Hand-edited, version-controlled |

---

## 6. Write-Back Model

### Safe auto-write (no validation needed)

| What | Where | Guard |
|------|-------|-------|
| Observations | `advisor_observations` | Always write. Model + confidence recorded. |
| Article metadata | `article_index` | Always write. URL uniqueness prevents duplicates. |
| Analyst consensus | `analyst_consensus_history` | Always write. One row/symbol/day. |
| Dividend history | `dividend_history` | Always write. One row/symbol/date. |
| Forecasts | `advisor_forecasts` | Write with `confidence` field. Revisit at horizon. |
| Sentiment scores | `social_sentiment_history` (future) | Always write. Timestamped. |

### Validated write (recommendation queue → human review)

| What | Where | Validation |
|------|-------|------------|
| Recommendations | `advisor_recommendations` (status='pending') | Agent writes as pending. User accepts/rejects via UI. |
| Email notifications | `notification_log` + Gmail send | Initially: all queued. After validation period: digests auto-send. |
| Thesis config changes | Proposed in recommendation | Always architect-approved. |

### Poisoning prevention

1. **Confidence floor:** Observations below 0.3 confidence are stored but never surfaced in recommendations
2. **Model provenance:** Every write records which model, which prompt, and input data hash
3. **Expiration:** Observations have `expires_at` — stale observations don't contribute to new recommendations
4. **Supersession:** New observations on the same topic can mark older ones as superseded
5. **Audit trail:** All writes are append-only. No deletes. Status changes are tracked.

---

## 7. Escalation Framework

### Trigger → Assess → Escalate → Validate → Act

```
[Local Monitor] → detects signal
    ↓
[Local Scoring] → assigns importance 0-1
    ↓
importance >= 0.6? → [Escalate to External Model]
    ↓
[External Synthesis] → generates recommendation + confidence
    ↓
confidence >= 0.7? → [Queue for User]
    ↓
[User Review] → accept / reject / defer
```

### Specific escalation triggers

| Trigger | Local Detection | External Question |
|---------|----------------|-------------------|
| Concentration crosses 15% | Monitor portfolio_pct daily | "Given current market and alternatives, is 15%+ in {sym} still thesis-aligned?" |
| Dividend yield drops >15% | Compare current vs 90-day avg | "Is this a temporary suppression or structural deterioration? What are alternatives?" |
| Analyst consensus shifts | Count upgrades/downgrades | "Does the consensus shift reflect new information or herding? What's the base case now?" |
| Signal persistence (TRIM 5+ days) | Count from action_signals_history | "User hasn't acted on TRIM signal for 5 days. Is the original thesis still valid? Reframe recommendation." |
| Better substitute appears | Score alternatives locally | "Compare {current} vs {candidate} on yield, growth, risk, thesis fit. Recommend rotation?" |
| Market regime change | VIX >30, breadth collapse | "Should portfolio shift defensive? Which holdings have most downside? Recommend allocation change?" |

### Cost awareness

- Local model: $0/call, unlimited
- Claude Sonnet: ~$0.03/call average, budget 100-200 calls/month
- GPT-4o: ~$0.02/call average, budget 100-200 calls/month
- Claude Opus: ~$0.15/call, budget 30-50 calls/month (monthly synthesis only)
- **Hard cap:** $30/month. Agent tracks spend in `notification_log` or separate `model_usage` table.

---

## 8. Gmail / User Notification Strategy

### Notification tiers

| Tier | Channel | Frequency | Example |
|------|---------|-----------|---------|
| **Urgent** | Gmail + Telegram | Immediate | Dividend cut announced, stop triggered, position halted |
| **Important** | Gmail | Same-day | New TRIM signal, analyst downgrade, rotation opportunity scores >0.8 |
| **Digest** | Gmail | Daily (7 AM) | Summary of observations, pending recommendations, forecast updates |
| **Weekly synthesis** | Gmail | Sunday evening | Week's performance, recommendation outcomes, next-week outlook |
| **Monthly review** | Gmail + DOCX attachment | 1st of month | Full portfolio review, forecast accuracy, advisor self-assessment |

### Quality gates before emailing

1. **Confidence >= 0.7** for any recommendation in the email
2. **Not duplicate** — check `notification_log` for same topic within 48h
3. **Materially new** — the finding must add information beyond what was sent before
4. **Position size gate** — don't email about positions <$5K unless urgent (stop/halt)
5. **Market hours context** — non-urgent findings held until next morning digest if after 8 PM

### Email format

```
Subject: [OpenClaw] {Urgent|Important|Digest}: {1-line summary}

Body:
- Finding (1-2 sentences)
- Evidence (bullet points with data)
- Recommendation (if any)
- Confidence level
- Action required (if any)
- Link to dashboard for details
```

---

## 9. Recommended Database Expansion Roadmap

Ranked by value for the advisor vision:

| Priority | Table/Entity | Why | Effort |
|----------|-------------|-----|--------|
| 1 | `dividend_history` | Income tracking continuity, yield deterioration detection | 2h |
| 2 | `advisor_observations` | Core memory — agent needs to record what it sees | 2h |
| 3 | `article_index` | Article dedup, relevance tracking, catalyst patterns | 3h |
| 4 | `advisor_recommendations` | Track what was recommended and outcomes | 2h |
| 5 | `analyst_consensus_history` | Detect analyst shifts, compare against price | 2h |
| 6 | `advisor_forecasts` | Self-assessment, accuracy tracking, outlook continuity | 2h |
| 7 | `notification_log` | Audit trail, dedup, delivery confirmation | 1h |
| 8 | `social_sentiment_history` | Social signal tracking (Reddit/StockTwits) | 3h |
| 9 | Merge `monthly_advisory` into `intel_briefs` | Advisor memory for "what did I say last month?" | 30min |

---

## 10. Phased Build Plan

### Phase A: Advisor-Memory Schema (1-2 days)

**Objective:** Create the core database tables for agent memory.  
**Deliverables:** `advisor_observations`, `advisor_recommendations`, `advisor_forecasts`, `notification_log`, `dividend_history`, `article_index`  
**Dependencies:** None (all additive)  
**Risk:** Low — just schema + empty tables  
**Usable at completion:** Tables ready for Phase C to write to

### Phase B: Article/Analyst/Social Ingestion (3-5 days)

**Objective:** Build ingestion pipelines for new data sources.  
**Deliverables:** Yahoo fundamentals scraper, analyst consensus tracker, social sentiment scorer, article indexer  
**Dependencies:** Phase A (tables exist)  
**Risk:** Medium — external API rate limits, data quality issues  
**Usable at completion:** Historical data accumulating; queryable analyst/social trends

### Phase C: Local-First Monitor + Scoring (5-7 days)

**Objective:** Build the Ollama-powered monitoring daemon that continuously scores observations.  
**Deliverables:** `openclaw_monitor.py` — runs on timer (every 30min market hours), scores all inputs, writes observations  
**Dependencies:** Phase A + B (data flowing)  
**Risk:** Medium — prompt engineering for reliable local scoring  
**Usable at completion:** Observations accumulating; "what did the agent notice today?" queryable

### Phase D: Escalation + Validation (3-5 days)

**Objective:** Build the external model escalation pipeline.  
**Deliverables:** Escalation router, Sonnet/GPT-4o integration, recommendation generation, confidence scoring  
**Dependencies:** Phase C (observations trigger escalation)  
**Risk:** Medium — cost management, recommendation quality  
**Usable at completion:** Recommendations generated; pending queue viewable

### Phase E: Gmail Notifications + Write-Back (2-3 days)

**Objective:** Wire Gmail send for digests and alerts.  
**Deliverables:** Gmail MCP integration, notification templates, delivery logging, digest scheduler  
**Dependencies:** Phase D (recommendations to notify about)  
**Risk:** Low — Gmail MCP already available in Claude Code  
**Usable at completion:** User receives daily digests and urgent alerts

### Phase F: Portfolio Rotation + Forecast Engine (5-8 days)

**Objective:** Build the comparison/rotation and multi-horizon forecast system.  
**Deliverables:** Alternative screener, rotation scorer, 1Y/2Y/3Y/5Y forecast generation, accuracy tracking  
**Dependencies:** Phase B (fundamentals), Phase D (external models for synthesis)  
**Risk:** High — forecast quality, avoiding overconfident rotation signals  
**Usable at completion:** Full advisor capability — proactive rotation proposals with forecasts

### Total estimated effort: 19-30 days across 6 phases

---

## 11. Risks and Guardrails

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Stale data driving recommendations** | HIGH | Freshness checks (Phase 0 already built). Agent checks `_freshness.json` before any recommendation. Observations expire. |
| **Hallucinated recommendations** | HIGH | All recommendations stored with evidence trail. Confidence threshold before surfacing. Human approval for first 30 days. |
| **Duplicate/contradictory memory** | MEDIUM | UNIQUE constraints on (date, symbol, horizon). Supersession chain for observations. |
| **Alert fatigue** | HIGH | Strict quality gates. Daily digest collects low-importance findings. Urgent alerts only for pre-defined triggers. |
| **Model cost explosion** | MEDIUM | Hard monthly cap ($30). Local tier handles 90%+. Escalation requires threshold. Track spend per model. |
| **Reddit/social noise** | MEDIUM | Sentiment scored locally first. Only unusual spikes (>3x baseline) escalate. Portfolio-relevance filter. |
| **Overfitting to analyst chatter** | MEDIUM | Consensus changes tracked as data, not treated as truth. Agent considers analyst track record. |
| **Unsafe auto-write** | LOW (by design) | Observations auto-write (safe). Recommendations require human acceptance. Trades never automated. |
| **Recommendation provenance loss** | LOW | Every entry records model, prompt hash, input data, confidence, timestamp. Append-only. |
| **Agent memory poisoning** | MEDIUM | Confidence floor (0.3). Expiration dates. Model provenance. Supersession chain. No deletes. |

---

## 12. Architect Recommendation

### Smallest high-value first slice

**Phase A (schema) + dividend_history ingestion + basic observation writer.**

This gives:
- Tables ready for all future phases
- Dividend yield tracking starts accumulating immediately (most time-sensitive data)
- A simple "observation writer" that records daily findings from existing pipeline data
- Foundation for everything else without any external API cost

### Highest-value database additions (do first)

1. `dividend_history` — yields change; tracking them early builds the most valuable time-series
2. `advisor_observations` — the agent's "working memory" — everything else builds on this
3. `article_index` — dedup + relevance tracking; enables "what did we already read about V?"

### Recommended next document or task

**Create `linux_port_v2/linux/db_setup_advisor.sql`** — the schema file for all Phase A tables. Separate from the existing `db_setup.sql` (which is now the "operational" schema). This establishes the boundary between "Trade AI operational data" and "OpenClaw advisor memory."

Then: implement the `dividend_history` ingestion from existing `dividend_calendar.json` data (daily writer, similar to existing dual-write pattern). This is the single highest-ROI first task because dividend yield data has the most compounding value over time.

---

## Appendix A: Proposed Core Entities

```
advisor_observations    — what the agent noticed (append-only)
advisor_recommendations — what the agent suggests (status-tracked)
advisor_forecasts       — multi-horizon projections (accuracy-tracked)
article_index           — every article consumed (deduped by URL)
analyst_consensus_history — target/rating snapshots per ticker per day
dividend_history        — yield/payment tracking per ticker over time
social_sentiment_history — Reddit/StockTwits pulse per ticker
notification_log        — audit trail of all user communications
model_usage_log         — cost tracking per model per day
```

## Appendix B: Proposed Confidence Levels

| Level | Range | Meaning | Agent Behavior |
|-------|-------|---------|----------------|
| Speculative | 0.00-0.29 | Weak signal, possible noise | Store as observation. Never surface. |
| Low | 0.30-0.49 | Interesting but unvalidated | Store. Include in digest if relevant. Don't escalate. |
| Moderate | 0.50-0.69 | Meaningful signal | Store. Include in digest. Escalate if position >5% of portfolio. |
| High | 0.70-0.89 | Strong evidence, validated | Generate recommendation. Queue for email. |
| Very High | 0.90-1.00 | Multiple confirming sources | Urgent alert. Email immediately (after validation period). |

## Appendix C: Proposed Escalation Severity

| Severity | Response | Email? | Example |
|----------|----------|:---:|---------|
| **S1 — Urgent** | Immediate notification | ✓ | Dividend cut, stop triggered, position halted, fraud alert |
| **S2 — Important** | Same-day notification | ✓ | Analyst downgrade cluster, rotation opportunity >0.8, yield deterioration |
| **S3 — Noteworthy** | Include in daily digest | In digest | Signal change, minor concentration drift, social spike |
| **S4 — Informational** | Store in memory only | No | Background observation, trend data point, forecast update |

---

*Planning brief created 2026-04-20. Awaiting architect approval before implementation.*
