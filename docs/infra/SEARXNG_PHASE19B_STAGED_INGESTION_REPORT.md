# SearXNG Phase 19B — First Capped Staged Ingestion Report

**Date:** 2026-05-31
**Status:** COMPLETE — 5 rows staged

## Inserted Rows

| ID | Symbol | Source Domain | Topic | Score | Status |
|----|--------|--------------|-------|-------|--------|
| 12 | SCHD | seekingalpha.com | Upgrade analysis — buying opportunity | 0.50 | staged |
| 13 | TRX | finance.yahoo.com | Q2 2026 earnings call highlights | 0.50 | staged |
| 14 | APAM | fool.com | Q1 2026 earnings transcript | 0.48 | staged |
| 15 | FJSCX | zacks.com | Fund holdings data | 0.48 | staged |
| 16 | TRX | seekingalpha.com | Catalyst analysis — down 60% from highs | 0.50 | staged |

## Target Table

`hermes_research_intelligence` — existing Hermes staging table

## Field Mapping

| Field | Value |
|-------|-------|
| source | 'hermes' (CHECK constraint) |
| hermes_agent_name | 'source_discovery_agent' |
| research_type | 'source_discovery' |
| model_used | 'searxng_manual' |
| status | 'staged' |
| tags | includes 'source_discovery', 'searxng', 'phase_19B', category |
| evidence_json | external_source type with discovery_method, snippet, advisory_only |
| source_urls_json | original article URL |

## Post-Ingestion State

| Metric | Before | After |
|--------|--------|-------|
| hermes_research_intelligence rows | 11 | 16 |
| Staged | 1 (TELO) | 6 (TELO + 5 source_discovery) |
| Promoted | 10 | 10 (unchanged) |
| llm_intelligence_cache hermes sections | 10 | 10 (unchanged) |
| content_embeddings hermes rows | 7 | 7 (unchanged) |

## Safety Confirmations

- [x] Exactly 5 rows inserted (at cap)
- [x] Target table: hermes_research_intelligence only
- [x] All rows status='staged'
- [x] No production table writes
- [x] No embeddings created
- [x] No promotions
- [x] No llm_intelligence_cache writes
- [x] No broker/proposal/trade/journal mutations
- [x] Rollback SQL ready

## Rollback

```bash
PGPASSWORD='...' psql -h localhost -U trade_ai -d trade_ai -f docs/infra/SEARXNG_PHASE19B_STAGED_INGESTION_ROLLBACK.sql
```
