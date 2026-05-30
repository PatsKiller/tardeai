# Hermes Phase 1F Session Closeout

**Date:** 2026-05-30
**Status:** CLOSED — Phase 1F batch research ingestion complete

---

## Phase 1F Summary

First Hermes batch research run. 5 tasks attempted via gemma3:12b local Ollama, 3 validated and staged, 2 rejected.

### Tasks

| # | Task | Symbol | Type | Status | Row ID |
|---|------|--------|------|--------|--------|
| 1 | Ticker thesis challenge | SPRC | ticker_thesis_challenge | STAGED | 2 |
| 2 | News reframe | SCHD | news_research_reframe | STAGED | 3 |
| 3 | Trade reflection | APPS | trade_reflection | STAGED | 4 |
| 4 | Pipeline validation | — | pipeline_quality_validation | REJECTED | — |
| 5 | Agent validation | — | pipeline_quality_validation | REJECTED | — |

### Rejections

Tasks 4 and 5 rejected: model returned empty `evidence_json` for system-level tasks. Non-ticker validation tasks need prompt refinement.

### Ingestion Script Fix

Removed `alpaca` from forbidden keyword list (false positive — `position_closed_in_alpaca` is a data value, not a mutation instruction).

---

## Current Hermes Row State

| Table | Rows | Details |
|-------|------|---------|
| hermes_research_intelligence | 4 | Phase 1E: id=1 (FLYW), Phase 1F: ids 2-4 (SPRC, SCHD, APPS) |
| hermes_validation_findings | 0 | — |
| hermes_alerts | 0 | — |
| hermes_embedding_queue | 0 | — |
| hermes_memory_events | 1 | Phase 1B smoke row |
| hermes_promotion_audit | 0 | — |

---

## Rollback

| File | Status |
|------|--------|
| `docs/hermes/HERMES_PHASE1F_BATCH_RESEARCH_INGESTION_ROLLBACK.sql` | Local — deletes ids 2, 3, 4 |
| `docs/hermes/HERMES_PHASE1F_BATCH_RESEARCH_INGESTION_ROLLBACK_SQL.md` | Drive wrapper — synced |

---

## Source Discovery Design

`docs/hermes/HERMES_SOURCE_DISCOVERY_AND_MEMORY_DESIGN.md` — design only, not implemented.

Covers: `hermes_research_sources` table, per-ticker source portfolios, quality scoring, seed URLs, 5-phase implementation plan.

---

## Headless Browser

Playwright + Chromium installed in sidecar. agent-browser npm package installed. Browser test PASS (Yahoo Finance AAPL). Hermes doctor confirms browser tool available.

---

## Safety

| Item | Status |
|------|--------|
| Production table writes | **ZERO** |
| content_embeddings writes | **ZERO** |
| Broker access | **ZERO** |
| Proposal mutations | **ZERO** |
| paper_trades mutations | **ZERO** |
| Journal mutations | **ZERO** |
| Cron changes | **ZERO** |
| Service/daemon changes | **ZERO** |
| External APIs | **ZERO** |

---

## Current Allowed State

- Hermes sidecar installed with headless browser
- 6 hermes_* staging tables with roles/grants
- 8 safe read views + 37 direct table SELECT grants
- Controlled staging ingestion script
- Hermes gateway on :18790, Chat page at /v2/hermes
- 4 staged research rows (advisory only)

## Current Prohibited State

- No embeddings
- No content_embeddings writes
- No production promotions
- No dashboard Hermes Challenger
- No daemon/service/cron
- No broker/proposal/trade/journal mutation
- No external API/web research via Hermes agents (browser capability installed but not agent-integrated)

---

## Open Risks

| Risk | Severity |
|------|----------|
| System-level validation tasks need prompt refinement | LOW |
| Backup schedule gap (last automated: April 21) | MEDIUM |
| Ollama GPU OOM at 131K context | LOW (capped at 8K for Hermes) |

---

## Next Recommended Gate

**Hermes Phase 1G — quality review of staged research before more ingestion.**

Scope: review Phase 1E+1F rows for usefulness, hallucination risk, evidence quality, actionability. No new ingestion, no embeddings, no promotion.
