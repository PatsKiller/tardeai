# Hermes Data Ingestion Architecture — Trade AI v12

**Date:** 2026-05-30
**Status:** ARCHITECTURE DESIGN — no tables created, no code changes, no install

---

## 1. Problem Statement

Hermes produces research intelligence (ticker analysis, trade reflections, news reframes, incubator reviews, strategy hypotheses). If this intelligence stays only in files, it is invisible to Trade AI's dashboards, agents, and decision pipeline.

A controlled ingestion path is needed so Hermes research can flow back into Trade AI — without violating Hermes' non-execution boundary.

---

## 2. Core Constraints

| Rule | Enforced |
|------|----------|
| Hermes has no execution authority | YES — permanent |
| Hermes has no broker access | YES — permanent |
| Hermes cannot mutate `paper_trade_proposals` | YES |
| Hermes cannot mutate `paper_trades` | YES |
| Hermes cannot mutate trade journal | YES |
| Hermes cannot mutate holdings | YES |
| Hermes cannot mutate broker state | YES |
| Hermes cannot change cron | YES |
| Hermes cannot change `.env` | YES |
| Hermes cannot change model routing | YES |
| Hermes may generate research intelligence | YES |
| Hermes research must be preservable and usable | YES |
| Ingestion must be staged and reviewable | YES |

---

## 3. Existing Table Compatibility Assessment

### Tables with source isolation (safe for eventual direct write)

| Table | Source Field | Hermes Value | Risk |
|-------|-------------|-------------|------|
| `news_articles` | `source` TEXT | `'hermes'` | LOW — existing queries filter by source |
| `content_embeddings` | `source_type` TEXT | `'hermes_research'` | LOW — append-only, source-partitioned |
| `intelligence_entities` | `pipeline_sources[]` | append `'hermes'` | LOW — array tracks all contributors |
| `agent_intelligence_rules` | `rule_type` TEXT | `'hermes_*'` namespace | LOW — namespaced, no collision |
| `deep_overnight_llm_results` | `source_table` + `source_id` | `'hermes_research'` + hermes ID | LOW — via queue, isolated |

### Tables without source isolation (risky for direct write)

| Table | Issue | Recommendation |
|-------|-------|----------------|
| `watchlist_agent_results` | No `source` column | DO NOT write directly — use staging |
| `llm_intelligence_cache` | Section name collision risk | DO NOT write directly — use staging |
| `paper_trade_multi_reviews` | No `source` column, tied to trade IDs | DO NOT write directly — use staging |

### Existing staging/outbox pattern

**None.** Trade AI writes directly to production tables. Hermes will be the first system to use a staging pattern — this is appropriate given its advisory-only role.

---

## 4. Recommended Architecture: Staged Ingestion

```
Hermes Agent → File Outbox (P0) → Staging Table (P1) → Promotion Script (P2) → Production Table (P3)
                  ↓                      ↓                      ↓                      ↓
           hermes_sidecar/        hermes_research_      operator approval       existing Trade AI
           research_outbox/       intelligence           required                tables + UI
```

### Phase P0 — File-Only Outbox

Hermes writes JSON and Markdown to the filesystem. No database involvement.

**Output directory:**

```
hermes_sidecar/research_outbox/
├── ticker_research/
│   └── AAPL_2026-05-30.json
├── trade_reflections/
│   └── reflection_2026-05-30.json
├── news_reframes/
│   └── reframe_2026-05-30_semiconductors.json
├── incubator_reviews/
│   └── PLTR_2026-05-30.json
├── strategy_hypotheses/
│   └── hypothesis_2026-05-30_rsi_threshold.json
├── coordinator_briefs/
│   └── daily_brief_2026-05-30.json
└── _manifest.jsonl   # append-only log of all outputs
```

**File format (JSON):**

```json
{
  "id": "hermes_20260530_ticker_AAPL_001",
  "created_at": "2026-05-30T14:30:00Z",
  "source": "hermes",
  "hermes_agent_name": "ticker_research_agent",
  "research_type": "ticker_dossier",
  "symbol": "AAPL",
  "related_trade_id": null,
  "related_proposal_id": null,
  "topic": "AAPL Q2 earnings catalyst assessment",
  "summary": "...",
  "thesis": "...",
  "evidence": [
    {"type": "news", "source_url": "...", "date": "...", "relevance": 0.8},
    {"type": "backtest", "trade_id": 42, "outcome": "win", "relevance": 0.9}
  ],
  "confidence_score": 0.72,
  "freshness_date": "2026-05-30",
  "source_urls": ["..."],
  "model_used": "gemma3:12b",
  "prompt_hash": "sha256:abc123...",
  "status": "staged",
  "promoted_to_table": null,
  "promoted_to_id": null,
  "reviewed_by": null,
  "reviewed_at": null
}
```

**Companion Markdown:**

Each JSON also produces a human-readable `.md` in `hermes_sidecar/reports/` (per existing pilot plan).

**P0 success criteria:**

- Hermes outputs valid JSON to outbox
- No DB writes
- Operator can review files manually
- Format is stable enough for P1 ingestion

---

### Phase P1 — DB Staging Table

Create Hermes-owned staging tables. Trade AI production tables are not touched.

**Primary staging table: `hermes_research_intelligence`**

```sql
CREATE TABLE hermes_research_intelligence (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source          TEXT NOT NULL DEFAULT 'hermes',
    hermes_agent_name TEXT NOT NULL,
    research_type   TEXT NOT NULL,
    symbol          TEXT,
    related_trade_id BIGINT,
    related_proposal_id BIGINT,
    topic           TEXT NOT NULL,
    summary         TEXT NOT NULL,
    thesis          TEXT,
    evidence_json   JSONB NOT NULL DEFAULT '[]',
    confidence_score REAL CHECK (confidence_score >= 0 AND confidence_score <= 1),
    freshness_date  DATE NOT NULL,
    source_urls_json JSONB DEFAULT '[]',
    model_used      TEXT NOT NULL,
    prompt_hash     TEXT,
    status          TEXT NOT NULL DEFAULT 'staged'
                    CHECK (status IN ('staged','reviewed','promoted','rejected','archived')),
    promoted_to_table TEXT,
    promoted_to_id  BIGINT,
    reviewed_by     TEXT,
    reviewed_at     TIMESTAMPTZ
);

CREATE INDEX idx_hermes_ri_status ON hermes_research_intelligence(status);
CREATE INDEX idx_hermes_ri_symbol ON hermes_research_intelligence(symbol);
CREATE INDEX idx_hermes_ri_type ON hermes_research_intelligence(research_type);
CREATE INDEX idx_hermes_ri_agent ON hermes_research_intelligence(hermes_agent_name);
CREATE INDEX idx_hermes_ri_created ON hermes_research_intelligence(created_at);
```

**Secondary staging table: `hermes_memory_events`**

```sql
CREATE TABLE hermes_memory_events (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type      TEXT NOT NULL,
    hermes_agent_name TEXT NOT NULL,
    symbol          TEXT,
    topic           TEXT NOT NULL,
    content         TEXT NOT NULL,
    metadata_json   JSONB DEFAULT '{}',
    expires_at      TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','expired','archived'))
);

CREATE INDEX idx_hermes_me_type ON hermes_memory_events(event_type);
CREATE INDEX idx_hermes_me_symbol ON hermes_memory_events(symbol);
CREATE INDEX idx_hermes_me_status ON hermes_memory_events(status);
```

**Allowed `research_type` values:**

| Value | Agent | Description |
|-------|-------|-------------|
| `ticker_dossier` | Ticker Research | Living ticker analysis |
| `news_reframe` | News Reframer | Reframed news summary |
| `transcript_brief` | News Reframer | Transcript summary |
| `incubator_review` | Incubator Research | Incubator challenge memo |
| `trade_reflection` | All-Trade Reflection | Closed trade postmortem |
| `missed_opportunity` | All-Trade Reflection | Missed trade analysis |
| `strategy_hypothesis` | Strategy Hypothesis | One-variable experiment |
| `daily_brief` | Coordinator | Daily research summary |
| `weekly_review` | Coordinator | Weekly synthesis |
| `challenge_memo` | Proposal Challenge | Proposal challenge note |
| `thesis_decay` | Thesis Decay | Thesis weakening alert |
| `regime_report` | Macro Research | Market regime assessment |
| `rotation_memo` | Portfolio Rotation | Rotation research |
| `tax_watchlist` | Tax/Lots Research | Tax-lot planning research |
| `data_freshness_warning` | Data Freshness Critic | Stale data alert |

**P1 ingestion script (runs on schedule or manually):**

```bash
# Reads from hermes_sidecar/research_outbox/*.json
# Inserts into hermes_research_intelligence with status='staged'
# Does NOT touch any production tables
python scripts/hermes_ingest_outbox.py
```

**P1 success criteria:**

- Staging table exists with proper schema
- Ingestion script reads file outbox → inserts staging rows
- All rows have `source='hermes'` and `status='staged'`
- No production table mutations

---

### Phase P2 — Reviewed Promotion

A separate promotion script moves reviewed Hermes intelligence into Trade AI production tables — only after operator approval.

**Promotion targets (safe tables only):**

| Staging `research_type` | Target Table | Target Field | Conditions |
|------------------------|-------------|-------------|------------|
| `news_reframe` | `news_articles` | `source='hermes'` | Operator reviewed, confidence ≥ 0.6 |
| `ticker_dossier` | `content_embeddings` | `source_type='hermes_research'` | Embed summary for RAG |
| `trade_reflection` | `agent_intelligence_rules` | `rule_type='hermes_trade_learning'` | Extract learning rules |
| `daily_brief` | `llm_intelligence_cache` | `section='hermes_daily_brief'` | Namespaced, no collision |
| `incubator_review` | `content_embeddings` | `source_type='hermes_incubator'` | Embed for RAG |

**Tables that are NEVER promotion targets:**

| Table | Reason |
|-------|--------|
| `paper_trade_proposals` | Execution boundary |
| `paper_trades` | Execution boundary |
| `trade_journal` | Execution boundary |
| `holdings` | Execution boundary |
| `broker_*` | Execution boundary |

**Promotion script behavior:**

```bash
# Requires explicit operator approval
python scripts/hermes_promote_reviewed.py --dry-run    # shows what would promote
python scripts/hermes_promote_reviewed.py --apply       # only after operator approval
```

```
For each row where status='reviewed':
  1. Map to target table
  2. Insert with source='hermes' / source_type='hermes_*'
  3. Update staging row: status='promoted', promoted_to_table, promoted_to_id
  4. Log promotion in audit trail
```

**P2 success criteria:**

- Promotion only runs with `--apply` flag after `--dry-run` review
- All promoted rows traceable back to staging ID
- Production tables show Hermes data with clear provenance
- No rows promoted without `status='reviewed'`

---

### Phase P3 — Dashboard Integration

Command Center shows Hermes intelligence as a separate, labeled source.

**UI requirements:**

- All Hermes-sourced data labeled with `[Hermes]` badge
- Hermes intelligence shown in separate cards/sections, not blended
- No Hermes data appears as if it came from Trade AI's own pipeline
- Provenance link back to staging table ID

**Suggested Command Center cards:**

| Card | Source |
|------|--------|
| Hermes Daily Brief | `hermes_research_intelligence WHERE research_type='daily_brief'` |
| Hermes Ticker Research | `hermes_research_intelligence WHERE research_type='ticker_dossier'` |
| Hermes Trade Lessons | `hermes_research_intelligence WHERE research_type='trade_reflection'` |
| Hermes Incubator Watch | `hermes_research_intelligence WHERE research_type='incubator_review'` |
| Hermes News Reframes | `hermes_research_intelligence WHERE research_type='news_reframe'` |
| Hermes Strategy Lab | `hermes_research_intelligence WHERE research_type='strategy_hypothesis'` |

**P3 success criteria:**

- Hermes data visible in Command Center
- All entries clearly labeled as Hermes-sourced
- No blending with Trade AI data without explicit provenance

---

## 5. Promotion Workflow

```
Hermes Agent
    ↓ writes JSON
File Outbox (hermes_sidecar/research_outbox/)
    ↓ ingestion script
Staging Table (hermes_research_intelligence, status='staged')
    ↓ operator reviews in Command Center or CLI
Status → 'reviewed' (operator marks as reviewed)
    ↓ promotion script --dry-run
Dry-run report shown to operator
    ↓ operator approves
Promotion script --apply
    ↓ inserts into target table with source='hermes'
Status → 'promoted', promoted_to_table, promoted_to_id recorded
```

**Rejection path:**

```
Operator reviews → marks status='rejected' with reason
Row stays in staging for audit, never promoted
```

**Archival path:**

```
After 30 days in 'promoted' or 'rejected' status → status='archived'
Archived rows remain queryable but not shown in active views
```

---

## 6. Risks

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| 1 | Hermes writes directly to production tables bypassing staging | HIGH | Code review: Hermes has no production DB credentials in P0; staging-only credentials in P1 |
| 2 | Promotion script runs without operator review | MEDIUM | `--dry-run` default; `--apply` requires explicit flag |
| 3 | Hermes data quality is poor, promoted data degrades Trade AI | MEDIUM | Confidence score filtering; operator review gate; 'rejected' status |
| 4 | Staging table grows unbounded | LOW | Archival policy (30 days); optional partition by month |
| 5 | File outbox fills disk | LOW | Monitor outbox size; archive after ingestion |
| 6 | Hermes and Trade AI race on Ollama | LOW | Manual runs during pilot; schedule coordination later |
| 7 | Promoted data loses provenance | LOW | `promoted_to_table` + `promoted_to_id` in staging row |

---

## 7. Revised Install Recommendation

The original install plan assumed Hermes was file-only. This architecture adds a DB staging layer (P1) and promotion workflow (P2). This does not change the install itself — it changes what happens after the pilot proves useful.

### Revised phasing

| Phase | Scope | DB Changes? | Install Required? |
|-------|-------|-------------|-------------------|
| **P0** | File-only pilot | NO | YES — Hermes install |
| **P1** | DB staging table | YES — create `hermes_research_intelligence` + `hermes_memory_events` | NO — migration script only |
| **P2** | Reviewed promotion | YES — promotion script writes to safe production tables | NO — script only |
| **P3** | Dashboard integration | YES — API endpoints + UI cards | NO — Trade AI code change |

### Should Hermes install wait for this architecture approval?

**NO.** The install can proceed independently. P0 is file-only — no database involvement. This architecture document governs P1+ only, which comes after P0 proves Hermes outputs are useful.

**Install order:**

1. Operator approves install → install Hermes (file-only, P0)
2. Run P0 pilot (file outbox, manual review)
3. Operator approves ingestion architecture → create staging tables (P1)
4. Run P1 (staged ingestion, operator review)
5. Operator approves promotion → enable promotion script (P2)
6. Operator approves dashboard → build UI cards (P3)

Each phase requires separate operator approval. The install does not commit to any database changes.

---

## 8. Summary

| Decision | Recommendation |
|----------|---------------|
| Ingestion architecture | Staged: file outbox → staging table → reviewed promotion → production |
| Direct writes to existing tables | **NO** — use staging first, even for safe tables |
| Staging schema | `hermes_research_intelligence` + `hermes_memory_events` |
| File outbox format | JSON with full provenance fields |
| Promotion workflow | Operator-reviewed, dry-run default, audit trail |
| Hermes install blocked by this? | **NO** — P0 is file-only, this governs P1+ |
| Tables created now? | **NO** — documentation only |
| Code changes now? | **NO** — documentation only |
