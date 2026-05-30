# Hermes Database-First Integration Architecture — Trade AI v12

**Date:** 2026-05-30
**Status:** ARCHITECTURE DESIGN — no tables created, no code changes, no install
**Supersedes:** `HERMES_DATA_INGESTION_ARCHITECTURE.md` (file-first design)

---

## 1. Design Principles

1. **Database-first.** Hermes intelligence lives in PostgreSQL, not files.
2. **Staging before production.** Hermes writes only to Hermes-owned tables. Promotion to production tables requires operator-reviewed scripts.
3. **Shared scoring logic.** Hermes calls existing Trade AI scoring functions read-only — no duplicated scoring code.
4. **Same embedding model.** Hermes uses nomic-embed-text (768-dim) via the same Ollama instance — embeddings are directly comparable.
5. **Provenance everywhere.** Every Hermes row carries `source='hermes'` and `hermes_agent_name`.
6. **Advisory only.** Hermes alerts are informational. No execution, no broker, no proposal mutation.
7. **File outbox is emergency fallback only** — not the primary architecture.

---

## 2. Read-Path: How Hermes Reads Trade AI Intelligence

Hermes reads Trade AI data through two channels: the HTTP API (primary) and read-only DB views (Phase 1+).

### 2.1 API Read Path (Phase 0+)

Hermes calls existing api_v2.py endpoints. No new endpoints required for Phase 0.

| Data | Endpoint | Key Fields |
|------|----------|------------|
| Portfolio holdings | `GET /api/v2/portfolio/holdings` | symbol, sector, RSI, beta, cost_basis, market_value, PI_score, LLM_health |
| Portfolio performance | `GET /api/v2/portfolio/performance` | period returns (YTD, 1Y, 3Y, 5Y), account breakdowns |
| Overview/dashboard | `GET /api/v2/overview` | portfolio_value, trade_ai run summary, journal stats, news_count |
| Ticker research | `GET /api/v2/research/ticker/{symbol}` | technicals, fundamentals, recent news (scored), performance |
| Watchlist + conviction | `GET /api/v2/watchlist/combined` | conviction_rating (0-100), LLM health, scan score, catalyst, social sentiment |
| Pending proposals | `GET /api/v2/approvals/pending` | strategy, grade, entry/stop/target, R:R, catalyst, screener source |
| Notifications | `GET /api/v2/notifications/recent` | source_script, alert_type, symbol |
| ATM readiness | `GET /api/v2/atm/execution-readiness` | pending proposals, approval status |
| Lifecycle inspector | `GET /api/v2/paper-proposals/lifecycle-inspector?proposal_id=N` | full proposal lifecycle |

### 2.2 New Read-Only API Endpoints (Phase 1)

These expose data Hermes needs that isn't currently available via API:

| Endpoint | Source Table | Purpose |
|----------|-------------|---------|
| `GET /api/v2/hermes/news?symbol=X&days=30` | `news_articles` | Extended news history with scores |
| `GET /api/v2/hermes/trades/closed?limit=50` | `paper_trades` WHERE lifecycle_state='closed' | Recent closed trade data |
| `GET /api/v2/hermes/trades/open` | `paper_trades` WHERE lifecycle_state='open' | Current open positions |
| `GET /api/v2/hermes/rag/query` | `content_embeddings` via `rag_retrieval.py` | RAG context retrieval |
| `GET /api/v2/hermes/intelligence/entities?symbol=X` | `intelligence_entities` | Entity intelligence scores |
| `GET /api/v2/hermes/overnight/results?days=7` | `deep_overnight_llm_results` | Recent deep analysis |
| `GET /api/v2/hermes/research/insights?symbol=X` | `research_insights` | Extracted research insights |
| `GET /api/v2/hermes/decisions?symbol=X` | `cio_decisions` | CIO decision history |
| `GET /api/v2/hermes/calibration` | `confidence_calibration_history` | Calibration data |
| `GET /api/v2/hermes/snapshots?symbol=X` | `ticker_snapshot_daily` | Daily technical snapshots |

All endpoints are read-only. No mutation. No authentication beyond localhost binding.

### 2.3 Direct DB Read Access (Phase 1+)

For batch research jobs (overnight, weekly), Hermes may read directly from the database using a **read-only PostgreSQL role**:

```sql
CREATE ROLE hermes_readonly WITH LOGIN PASSWORD '...';
GRANT CONNECT ON DATABASE trade_ai TO hermes_readonly;
GRANT USAGE ON SCHEMA public TO hermes_readonly;

-- Read-only on all existing tables
GRANT SELECT ON ALL TABLES IN SCHEMA public TO hermes_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO hermes_readonly;

-- Write access ONLY to Hermes-owned tables (created later)
-- GRANT INSERT, UPDATE ON hermes_research_intelligence TO hermes_readonly;
-- etc.
```

This role can SELECT from any table but cannot INSERT/UPDATE/DELETE production tables.

### 2.4 Context Engine Integration

Hermes should call `build_context()` from `llm_context_engine.py` for consistent data formatting. This function:

- Assembles symbol snapshots, trade history, news, portfolio context, recovery data, proposal data
- Applies anti-hallucination instructions
- Returns formatted text blocks ready for LLM prompts

**Integration:** Hermes imports `build_context()` read-only. It does not modify the context engine.

```python
from scripts.llm_context_engine import build_context

context = build_context(
    symbol='AAPL',
    context_type='trade_review',
    conn=hermes_readonly_conn
)
```

---

## 3. Write-Path: How Hermes Writes Research Without Corrupting Trade AI

### 3.1 Write Rules

| Rule | Enforcement |
|------|------------|
| Hermes writes ONLY to `hermes_*` tables | DB role: write granted only on hermes_* tables |
| Every row has `source='hermes'` | NOT NULL DEFAULT constraint |
| Every row has `hermes_agent_name` | NOT NULL constraint |
| No writes to `paper_trade_proposals` | DB role: no INSERT/UPDATE/DELETE |
| No writes to `paper_trades` | DB role: no INSERT/UPDATE/DELETE |
| No writes to trade journal tables | DB role: no INSERT/UPDATE/DELETE |
| No writes to `alert_events` | DB role: no INSERT/UPDATE/DELETE (Hermes has its own alert table) |
| No writes to holdings/broker tables | DB role: no INSERT/UPDATE/DELETE |

### 3.2 Hermes Write Targets

Hermes writes to 6 tables, all prefixed `hermes_`:

```
hermes_research_intelligence  — primary research output
hermes_validation_findings    — Trade AI validation/challenge results
hermes_alerts                 — advisory alerts for dashboard
hermes_embedding_queue        — embeddings awaiting indexing
hermes_memory_events          — durable memory log
hermes_promotion_audit        — promotion tracking and audit trail
```

---

## 4. Proposed Schema

### 4.1 `hermes_research_intelligence`

**Purpose:** Primary staging table for all Hermes research output — ticker dossiers, trade reflections, news reframes, incubator reviews, strategy hypotheses, daily briefs.

**Hermes may write:** YES
**Trade AI may promote from:** YES (via reviewed promotion script)

```sql
CREATE TABLE hermes_research_intelligence (
    id                    BIGSERIAL PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source                TEXT NOT NULL DEFAULT 'hermes',
    hermes_agent_name     TEXT NOT NULL,
    research_type         TEXT NOT NULL,
    symbol                TEXT,
    related_trade_id      BIGINT,
    related_proposal_id   BIGINT,
    topic                 TEXT NOT NULL,
    summary               TEXT NOT NULL,
    thesis                TEXT,
    thesis_type           TEXT CHECK (thesis_type IN ('bullish','bearish','neutral','mixed')),
    evidence_json         JSONB NOT NULL DEFAULT '[]',
    confidence_score      REAL CHECK (confidence_score >= 0 AND confidence_score <= 1),
    freshness_date        DATE NOT NULL,
    source_urls_json      JSONB DEFAULT '[]',
    model_used            TEXT NOT NULL,
    prompt_hash           TEXT,
    context_type_used     TEXT,
    status                TEXT NOT NULL DEFAULT 'staged'
                          CHECK (status IN ('staged','reviewed','promoted','rejected','archived')),
    promoted_to_table     TEXT,
    promoted_to_id        BIGINT,
    reviewed_by           TEXT,
    reviewed_at           TIMESTAMPTZ,
    quality_score         REAL,
    tags                  TEXT[] DEFAULT '{}',
    strategy_tags         TEXT[] DEFAULT '{}',
    agent_tags            TEXT[] DEFAULT '{}'
);

CREATE INDEX idx_hri_status ON hermes_research_intelligence(status);
CREATE INDEX idx_hri_symbol ON hermes_research_intelligence(symbol);
CREATE INDEX idx_hri_type ON hermes_research_intelligence(research_type);
CREATE INDEX idx_hri_agent ON hermes_research_intelligence(hermes_agent_name);
CREATE INDEX idx_hri_created ON hermes_research_intelligence(created_at DESC);
CREATE INDEX idx_hri_confidence ON hermes_research_intelligence(confidence_score DESC);
CREATE INDEX idx_hri_trade ON hermes_research_intelligence(related_trade_id) WHERE related_trade_id IS NOT NULL;
CREATE INDEX idx_hri_proposal ON hermes_research_intelligence(related_proposal_id) WHERE related_proposal_id IS NOT NULL;
```

**Allowed `research_type` values:**

| Value | Agent | Maps to Production Table |
|-------|-------|--------------------------|
| `ticker_dossier` | Ticker Research | `research_insights` (via promotion) |
| `news_reframe` | News Reframer | `content_embeddings` (via embedding queue) |
| `transcript_brief` | News Reframer | `content_embeddings` (via embedding queue) |
| `incubator_review` | Incubator Research | `content_embeddings` (via embedding queue) |
| `trade_reflection` | All-Trade Reflection | `agent_intelligence_rules` rule_type='hermes_trade_learning' |
| `missed_opportunity` | All-Trade Reflection | `decision_outcomes` (via promotion) |
| `strategy_hypothesis` | Strategy Hypothesis | `agent_intelligence_rules` rule_type='hermes_hypothesis' |
| `daily_brief` | Coordinator | `llm_intelligence_cache` section='hermes_daily_brief' |
| `weekly_review` | Coordinator | `llm_intelligence_cache` section='hermes_weekly_review' |
| `challenge_memo` | Proposal Challenge | no promotion — advisory only |
| `thesis_decay` | Thesis Decay | no promotion — advisory only |
| `regime_report` | Macro Research | `llm_intelligence_cache` section='hermes_regime' |
| `rotation_memo` | Portfolio Rotation | no promotion — advisory only |
| `tax_watchlist` | Tax/Lots Research | no promotion — advisory only |
| `data_freshness_warning` | Data Freshness Critic | `hermes_alerts` (cross-posted) |

### 4.2 `hermes_validation_findings`

**Purpose:** Hermes validation of Trade AI data quality, consistency, and evidence strength. This is the "challenger" output.

**Hermes may write:** YES
**Trade AI may promote from:** YES (findings can become `alert_events` via promotion)

```sql
CREATE TABLE hermes_validation_findings (
    id                    BIGSERIAL PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source                TEXT NOT NULL DEFAULT 'hermes',
    hermes_agent_name     TEXT NOT NULL,
    finding_type          TEXT NOT NULL CHECK (finding_type IN (
        'stale_data',
        'conflicting_agents',
        'weak_evidence',
        'scoring_inconsistency',
        'missing_source_link',
        'stale_proposal',
        'outdated_rag',
        'unsupported_thesis',
        'broken_pipeline',
        'missing_data',
        'hallucination_risk',
        'confidence_drift'
    )),
    severity              TEXT NOT NULL CHECK (severity IN ('info','warning','urgent','critical')),
    symbol                TEXT,
    affected_table        TEXT,
    affected_id           BIGINT,
    description           TEXT NOT NULL,
    evidence_json         JSONB NOT NULL DEFAULT '{}',
    recommended_action    TEXT,
    auto_fixable          BOOLEAN DEFAULT FALSE,
    status                TEXT NOT NULL DEFAULT 'open'
                          CHECK (status IN ('open','acknowledged','resolved','dismissed','promoted')),
    resolved_by           TEXT,
    resolved_at           TIMESTAMPTZ,
    promoted_to_alert_id  BIGINT
);

CREATE INDEX idx_hvf_status ON hermes_validation_findings(status);
CREATE INDEX idx_hvf_severity ON hermes_validation_findings(severity);
CREATE INDEX idx_hvf_symbol ON hermes_validation_findings(symbol);
CREATE INDEX idx_hvf_type ON hermes_validation_findings(finding_type);
CREATE INDEX idx_hvf_created ON hermes_validation_findings(created_at DESC);
CREATE INDEX idx_hvf_affected ON hermes_validation_findings(affected_table, affected_id);
```

### 4.3 `hermes_alerts`

**Purpose:** Advisory alerts for the Command Center dashboard. Separate from `alert_events` to prevent contamination of Trade AI's alert pipeline and Telegram routing.

**Hermes may write:** YES
**Trade AI may promote from:** YES (can copy to `alert_events` with source_script='hermes_promotion')

```sql
CREATE TABLE hermes_alerts (
    id                    BIGSERIAL PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source                TEXT NOT NULL DEFAULT 'hermes',
    hermes_agent_name     TEXT NOT NULL,
    alert_type            TEXT NOT NULL CHECK (alert_type IN (
        'research_finding',
        'validation_warning',
        'thesis_decay',
        'data_staleness',
        'missing_evidence',
        'scoring_drift',
        'regime_change',
        'incubator_signal',
        'trade_lesson',
        'portfolio_risk',
        'opportunity_alert'
    )),
    severity              TEXT NOT NULL CHECK (severity IN ('info','warning','urgent')),
    symbol                TEXT,
    title                 TEXT NOT NULL,
    description           TEXT NOT NULL,
    evidence_json         JSONB DEFAULT '{}',
    recommended_action    TEXT,
    confidence_score      REAL,
    related_research_id   BIGINT REFERENCES hermes_research_intelligence(id),
    related_finding_id    BIGINT REFERENCES hermes_validation_findings(id),
    status                TEXT NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active','read','dismissed','promoted')),
    read_at               TIMESTAMPTZ,
    dismissed_by          TEXT,
    promoted_to_alert_id  BIGINT
);

CREATE INDEX idx_ha_status ON hermes_alerts(status);
CREATE INDEX idx_ha_severity ON hermes_alerts(severity);
CREATE INDEX idx_ha_symbol ON hermes_alerts(symbol);
CREATE INDEX idx_ha_type ON hermes_alerts(alert_type);
CREATE INDEX idx_ha_created ON hermes_alerts(created_at DESC);
```

**Note:** `severity` does not include `'critical'`. Hermes cannot issue critical alerts — only Trade AI's own monitoring can.

### 4.4 `hermes_embedding_queue`

**Purpose:** Queue for Hermes research that should be embedded into `content_embeddings` for RAG retrieval. Embeddings are computed by Trade AI's existing embedding pipeline, not by Hermes directly.

**Hermes may write:** YES (queue items)
**Trade AI may promote from:** YES (embedding worker reads queue, writes to `content_embeddings` with `source_type='hermes_*'`)

```sql
CREATE TABLE hermes_embedding_queue (
    id                    BIGSERIAL PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source                TEXT NOT NULL DEFAULT 'hermes',
    source_research_id    BIGINT NOT NULL REFERENCES hermes_research_intelligence(id),
    title                 TEXT NOT NULL,
    content               TEXT NOT NULL,
    source_type_target    TEXT NOT NULL DEFAULT 'hermes_research',
    embedding_status      TEXT NOT NULL DEFAULT 'pending'
                          CHECK (embedding_status IN ('pending','processing','completed','failed','skipped')),
    embedded_id           BIGINT,
    embedded_at           TIMESTAMPTZ,
    error_message         TEXT
);

CREATE INDEX idx_heq_status ON hermes_embedding_queue(embedding_status);
CREATE INDEX idx_heq_created ON hermes_embedding_queue(created_at);
```

### 4.5 `hermes_memory_events`

**Purpose:** Durable memory log for Hermes agent state, operator decisions, recommendation outcomes, and lessons learned.

**Hermes may write:** YES
**Trade AI may promote from:** NO — internal Hermes state only

```sql
CREATE TABLE hermes_memory_events (
    id                    BIGSERIAL PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source                TEXT NOT NULL DEFAULT 'hermes',
    hermes_agent_name     TEXT NOT NULL,
    event_type            TEXT NOT NULL CHECK (event_type IN (
        'recommendation_issued',
        'operator_decision',
        'outcome_observed',
        'lesson_learned',
        'confidence_adjustment',
        'agent_state_change',
        'research_debt_logged',
        'do_not_repeat'
    )),
    symbol                TEXT,
    topic                 TEXT NOT NULL,
    content               TEXT NOT NULL,
    metadata_json         JSONB DEFAULT '{}',
    related_research_id   BIGINT REFERENCES hermes_research_intelligence(id),
    expires_at            TIMESTAMPTZ,
    status                TEXT NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active','expired','archived'))
);

CREATE INDEX idx_hme_type ON hermes_memory_events(event_type);
CREATE INDEX idx_hme_symbol ON hermes_memory_events(symbol);
CREATE INDEX idx_hme_status ON hermes_memory_events(status);
CREATE INDEX idx_hme_created ON hermes_memory_events(created_at DESC);
```

### 4.6 `hermes_promotion_audit`

**Purpose:** Full audit trail of every promotion from Hermes staging tables into Trade AI production tables.

**Hermes may write:** NO — only the promotion script writes here
**Trade AI may promote from:** N/A — this IS the audit table

```sql
CREATE TABLE hermes_promotion_audit (
    id                    BIGSERIAL PRIMARY KEY,
    promoted_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_table          TEXT NOT NULL,
    source_id             BIGINT NOT NULL,
    target_table          TEXT NOT NULL,
    target_id             BIGINT,
    promotion_type        TEXT NOT NULL CHECK (promotion_type IN (
        'research_to_insight',
        'research_to_embedding',
        'research_to_rule',
        'research_to_cache',
        'finding_to_alert',
        'alert_to_alert_event'
    )),
    dry_run               BOOLEAN NOT NULL DEFAULT TRUE,
    approved_by           TEXT,
    approved_at           TIMESTAMPTZ,
    rollback_sql          TEXT,
    notes                 TEXT
);

CREATE INDEX idx_hpa_source ON hermes_promotion_audit(source_table, source_id);
CREATE INDEX idx_hpa_target ON hermes_promotion_audit(target_table, target_id);
CREATE INDEX idx_hpa_promoted ON hermes_promotion_audit(promoted_at DESC);
```

---

## 5. Embedding / RAG Integration

### 5.1 Same Model, Same Dimensions

Hermes must use the same embedding model as Trade AI:

| Parameter | Value |
|-----------|-------|
| Model | `nomic-embed-text` via Ollama |
| Dimensions | 768 |
| Endpoint | `http://127.0.0.1:11434/api/embed` |
| Storage | `content_embeddings` table (after promotion) |
| Retrieval | `rag_retrieval.py` → `get_rag_context()` |

Using the same model ensures Hermes embeddings are directly comparable to Trade AI embeddings — cosine similarity works correctly across sources.

### 5.2 Embedding Flow

```
Hermes Research Output
    ↓ writes to hermes_research_intelligence (status='staged')
    ↓ writes to hermes_embedding_queue (embedding_status='pending')
    ↓
Trade AI Embedding Worker (scheduled)
    ↓ reads hermes_embedding_queue WHERE embedding_status='pending'
    ↓ calls _get_embedding(content) via nomic-embed-text
    ↓ inserts into content_embeddings with source_type='hermes_research'
    ↓ updates hermes_embedding_queue: embedding_status='completed', embedded_id=N
    ↓ writes hermes_promotion_audit row
```

### 5.3 RAG Retrieval with Hermes Data

Once Hermes research is embedded in `content_embeddings`, Trade AI's existing `get_rag_context()` will naturally retrieve it because:

1. The function queries `content_embeddings` filtered by symbol and recency
2. Hermes rows have `source_type='hermes_research'`
3. Source boosts in `rag_retrieval.py` can be configured:

```python
SOURCE_BOOSTS = {
    # existing
    "trade_outcome": 1.35,
    "news": 1.0,
    # new — Hermes sources start at neutral, adjust after quality validation
    "hermes_research": 1.0,
    "hermes_incubator": 1.0,
    "hermes_reflection": 1.05,
}
```

### 5.4 Quality Gate Before RAG Inclusion

Not all Hermes research should enter RAG. Only `status='promoted'` rows should be embedded:

| Gate | Criteria |
|------|----------|
| Minimum confidence | `confidence_score >= 0.5` |
| Status | `status = 'reviewed'` or `'promoted'` |
| Not rejected | `status != 'rejected'` |
| Not stale | `freshness_date` within 90 days |
| Operator approved | Promotion script ran with `--apply` |

---

## 6. Shared Scoring Logic

### 6.1 Existing Scoring Functions Hermes Should Call (Read-Only)

| Function | Module | Purpose | Hermes Use |
|----------|--------|---------|------------|
| `score_content()` | `content_scoring.py` | Quality + relevance score for text | Score Hermes research output for self-assessment |
| `tag_content()` | `content_scoring.py` | Strategy and agent tag extraction | Tag Hermes research with strategy/agent relevance |
| `get_rag_context()` | `rag_retrieval.py` | RAG retrieval with scoring | Retrieve context for Hermes analysis |
| `build_context()` | `llm_context_engine.py` | LLM prompt data assembly | Build data context for Hermes LLM calls |
| `_compute_intelligence_score()` | `intelligence_entity_manager.py` | Entity intelligence grade | Compare Hermes assessment vs Trade AI grade |

### 6.2 Hermes Should NOT Duplicate

| Logic | Why Not |
|-------|---------|
| Content scoring formula | Already in `content_scoring.py` — import it |
| RAG retrieval scoring | Already in `rag_retrieval.py` — call it |
| Intelligence grading (A+/A/B/C/D) | Already in `intelligence_entity_manager.py` — compare against it |
| Conviction rating (0-100) | Already in `api_v2.py` watchlist_combined — read it |
| Anti-hallucination instructions | Already in `llm_context_engine.py` — use build_context() |

### 6.3 Shared Confidence Scale

All Hermes confidence_score values use the same 0.0–1.0 scale as Trade AI:

| Range | Meaning | Trade AI Equivalent |
|-------|---------|---------------------|
| 0.0–0.3 | Low confidence | `low_confidence` validation status |
| 0.3–0.6 | Moderate | Below `ai_validated` threshold |
| 0.6–0.8 | High | `ai_validated` (quality ≥ 60, relevance ≥ 0.3) |
| 0.8–1.0 | Very high | Strong evidence, multiple sources |

Hermes can later cross-check its confidence against `confidence_calibration_history` to measure drift.

### 6.4 Hermes Self-Scoring

Before writing research output, Hermes runs `score_content()` on its own summary/thesis and stores the result in `quality_score`. This allows comparison against Trade AI's scoring of the same content.

```python
from scripts.content_scoring import score_content, tag_content

scores = score_content(title=topic, text=summary, source='hermes')
tags = tag_content(text=summary, title=topic)

row.quality_score = scores['quality_score']
row.tags = tags.get('strategy_tags', [])
row.agent_tags = tags.get('agent_tags', [])
```

---

## 7. Hermes Validation and Dashboard Alert Design

### 7.1 What Hermes Validates

| Validation Type | Source Data | Detection Method |
|----------------|------------|-----------------|
| Stale data | `ticker_snapshot_daily.snapshot_date` | Age > threshold per data type |
| Conflicting agents | `watchlist_agent_results`, `cio_decisions` | Contradictory recommendations for same symbol |
| Weak evidence | `research_insights.confidence` | Confidence < 0.3 with high-impact recommendation |
| Scoring inconsistency | `intelligence_entities.intelligence_score` | Grade changes > 2 levels in 24h |
| Missing source links | `research_insights.source_id` | NULL source or broken FK |
| Stale proposals | `paper_trade_proposals.created_at` | Age > strategy-specific threshold |
| Outdated RAG | `content_embeddings.created_at` | Symbol has no embeddings < 30 days |
| Unsupported thesis | `research_insights.key_arguments` | Empty arguments with high confidence |
| Broken pipeline | `deep_overnight_llm_queue.status` | Failed/stuck jobs > threshold |
| Missing data | `ticker_snapshot_daily` | Key symbols with no snapshot in 24h |
| Hallucination risk | `paper_trade_multi_reviews.review_text` | Claims not grounded in `build_context()` data |
| Confidence drift | `confidence_calibration_history` | Predicted vs actual divergence > 0.2 |

### 7.2 Dashboard Alert Flow

```
Hermes Validation Agent
    ↓ writes to hermes_validation_findings
    ↓ if severity >= 'warning', also writes to hermes_alerts
    ↓
Command Center Dashboard
    ↓ queries hermes_alerts WHERE status='active'
    ↓ displays in "Hermes Challenger" panel
    ↓ operator can: read → dismiss → or approve promotion to alert_events
```

### 7.3 Dashboard UI Design

**"Hermes Challenger" panel** in Command Center:

```
┌─────────────────────────────────────────────────┐
│  🔬 Hermes Challenger                    [3 new] │
├─────────────────────────────────────────────────┤
│  ⚠ AAPL thesis decay — catalyst expired   [warn]│
│    Evidence: earnings beat priced in, RSI 72     │
│    Recommended: review position thesis           │
│    Confidence: 0.71  |  Agent: thesis_decay      │
│    [Dismiss] [Acknowledge] [Promote to Alert]    │
├─────────────────────────────────────────────────┤
│  ℹ Stale RAG: PLTR — no embeddings < 30 days    │
│    [Dismiss] [Acknowledge]                       │
├─────────────────────────────────────────────────┤
│  ⚠ Scoring drift: defense_thesis +15pts/24h     │
│    [Dismiss] [Acknowledge] [Promote to Alert]    │
└─────────────────────────────────────────────────┘
```

All entries clearly labeled as Hermes-sourced. No blending with Trade AI alerts.

---

## 8. Phase Gates

### Phase 0 — Install and Smoke Test

| Item | Detail |
|------|--------|
| Hermes installed | Project-scoped in `hermes_sidecar/` |
| DB access | None — API-only reads |
| DB writes | None |
| Output | Console/log only |
| Validation | `hermes version`, `hermes doctor`, context test |
| Gate | Hermes runs, reads API, does not write outside sidecar |

### Phase 1 — Hermes-Owned Staging Tables

| Item | Detail |
|------|--------|
| DB migration | Create 6 `hermes_*` tables |
| DB role | `hermes_readonly` with SELECT on all + INSERT/UPDATE on hermes_* only |
| Read path | API + direct DB reads via hermes_readonly role |
| Write path | hermes_* tables only |
| Context engine | Hermes calls `build_context()` read-only |
| Scoring | Hermes calls `score_content()` and `tag_content()` read-only |
| Output | Rows in `hermes_research_intelligence`, `hermes_validation_findings`, `hermes_alerts` |
| Gate | Operator reviews staging data quality for ≥ 3 days |

### Phase 2 — Reviewed Promotion

| Item | Detail |
|------|--------|
| Promotion script | `scripts/hermes_promote_reviewed.py` |
| Default mode | `--dry-run` (prints intended actions) |
| Execute mode | `--apply` (requires explicit flag) |
| Targets | `research_insights`, `content_embeddings`, `agent_intelligence_rules`, `llm_intelligence_cache` |
| Never targets | `paper_trade_proposals`, `paper_trades`, journal, broker, holdings |
| Audit | Every promotion logged in `hermes_promotion_audit` |
| Rollback SQL | Stored per promotion row |
| Gate | Operator approves `--apply` run |

### Phase 3 — Dashboard Integration

| Item | Detail |
|------|--------|
| New API endpoints | `GET /api/v2/hermes/alerts`, `GET /api/v2/hermes/research`, `GET /api/v2/hermes/findings` |
| UI panel | "Hermes Challenger" card in Command Center |
| Provenance | All Hermes data labeled with `[Hermes]` badge |
| Blending | None — Hermes data shown separately |
| Gate | Operator approves dashboard design |

### Phase 4 — RAG Integration

| Item | Detail |
|------|--------|
| Embedding worker | Reads `hermes_embedding_queue`, embeds via nomic-embed-text |
| Target table | `content_embeddings` with `source_type='hermes_research'` |
| RAG boost | `hermes_research: 1.0` (neutral, adjustable after quality validation) |
| Quality gate | Only `status='promoted'` + `confidence >= 0.5` rows |
| Gate | Operator approves after verifying embedding quality |

---

## 9. Risks and Mitigations

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| 1 | Hermes bypasses staging, writes to production | HIGH | `hermes_readonly` DB role has no INSERT on production tables |
| 2 | Promotion runs without review | MEDIUM | `--dry-run` default; `--apply` requires explicit flag; audit trail |
| 3 | Hermes embeddings pollute RAG quality | MEDIUM | Quality gate (confidence ≥ 0.5, status='promoted'); source boost starts at 1.0 |
| 4 | Hermes and Trade AI race on Ollama | MEDIUM | Phase 0-1: manual runs; later: schedule coordination |
| 5 | Hermes duplicates scoring logic | LOW | Design: import existing functions, do not rewrite |
| 6 | Hermes validation false positives flood dashboard | LOW | Severity caps (no 'critical'); dismissal workflow; confidence threshold |
| 7 | Staging tables grow unbounded | LOW | 90-day archival policy; monthly partition option |
| 8 | Hermes reads stale API data | LOW | Freshness check on snapshot_date in API responses |
| 9 | Hermes context exceeds model capacity | LOW | gemma3:12b supports 131K; Hermes config caps at 65K |
| 10 | Promotion rollback fails | LOW | Rollback SQL stored per promotion row; dry-run first |

---

## 10. Install Recommendation

**Proceed with install.** The database-first architecture does not block installation:

- **Phase 0 requires no database changes.** Hermes reads via API only, writes nothing.
- **Phase 1 migration is a separate operator-approved step** after P0 proves Hermes runs cleanly.
- **File outbox remains as emergency fallback** if DB is unavailable, but is not the primary path.

### Install order

1. **Operator approves install** → install Hermes (Phase 0, API-read only)
2. **Run P0 pilot** — verify smoke test, API reads, no side effects
3. **Operator approves Phase 1** → create hermes_* tables + hermes_readonly role
4. **Run Phase 1** — Hermes writes to staging tables, operator reviews
5. **Operator approves Phase 2** → enable promotion script
6. **Operator approves Phase 3** → dashboard integration
7. **Operator approves Phase 4** → RAG embedding integration

Each phase requires separate, explicit operator approval. No phase auto-escalates.

---

## 11. Relationship to Previous Architecture Doc

`HERMES_DATA_INGESTION_ARCHITECTURE.md` proposed a file-first design. This document supersedes it:

| Decision | File-First (superseded) | Database-First (current) |
|----------|------------------------|--------------------------|
| Primary storage | JSON files in research_outbox/ | `hermes_research_intelligence` table |
| Embedding | Separate hermes_embeddings | Same `content_embeddings` table via queue |
| Scoring | Hermes computes independently | Hermes calls existing `score_content()` |
| Alerts | File-based | `hermes_alerts` table |
| Validation | Not designed | `hermes_validation_findings` table |
| RAG integration | Not designed | Via `hermes_embedding_queue` → `content_embeddings` |
| Promotion audit | Basic | Full `hermes_promotion_audit` table |
| File outbox | Primary | Emergency fallback only |
