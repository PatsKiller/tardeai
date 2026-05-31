# Hermes Phase 1H Session Closeout

**Date:** 2026-05-30
**Status:** CLOSED — prompt hardening + limited ingestion complete

---

## Objective

Harden Hermes research prompts and validators based on Phase 1G quality findings, then run a capped post-hardening ingestion batch to verify improvements.

---

## Part A: Prompt Hardening

| Item | Result |
|------|--------|
| Prompt template | `scripts/hermes_research_prompt.py` — facts/inferences separation, assertive findings, missing-data checklist, confidence explanation |
| Validator | `scripts/hermes_staging_ingest.py` — 7 new checks added |
| Tests | 9/9 pass |

### New Validator Checks

1. Evidence depth (≥ 2 substantive keys)
2. Limitations required non-empty
3. High confidence (> 0.85) requires ≥ 3 evidence refs
4. Question-style challenge_points rejected
5. External unsupported claims rejected
6. Source_views required non-empty
7. Credential pattern detection

---

## Part B: Limited Ingestion

| Task | Symbol | Type | Status | Row ID |
|------|--------|------|--------|--------|
| phase1h_task_01 | INFU | ticker_thesis_challenge | STAGED | 5 |
| phase1h_task_02 | ASPN | trade_reflection | STAGED | 6 |
| phase1h_task_03 | — | pipeline_quality_validation | STAGED | 7 |

**3/3 validated and staged (100% vs 60% in Phase 1F).**

---

## Row Counts

| Table | Before | After |
|-------|--------|-------|
| hermes_research_intelligence | 4 | **7** |
| hermes_memory_events | 1 | 1 |
| All others | 0 | 0 |

---

## Safety

| Item | Status |
|------|--------|
| Model used | gemma3:12b (local) |
| External APIs | **ZERO** |
| Embeddings | **ZERO** |
| content_embeddings writes | **ZERO** |
| Production writes | **ZERO** |
| Broker access | **ZERO** |
| Proposal mutations | **ZERO** |
| paper_trades mutations | **ZERO** |
| Journal mutations | **ZERO** |
| Cron/service/daemon changes | **ZERO** |

---

## Rollback

`docs/hermes/HERMES_PHASE1H_PROMPT_HARDENING_AND_LIMITED_INGESTION_ROLLBACK.sql` — deletes ids 5, 6, 7.

---

## Commit & Sync

| Item | Value |
|------|-------|
| Phase 1H commit | `dc64f2e` |
| Drive sync | Done — 10 uploaded |

---

## Current Allowed State

- Hermes sidecar installed with headless browser
- Gateway on :18790 (systemd, auto-restart, linger)
- 6 staging tables, 8 safe views, 37 direct table grants
- Controlled staging ingestion with hardened validator (9/9 tests)
- 7 staged research rows (FLYW, SPRC, SCHD, APPS, INFU, ASPN, pipeline)
- Chat page at /v2/hermes with two-step browse proxy

## Current Prohibited State

- No embeddings or content_embeddings writes
- No production promotion
- No dashboard Hermes Challenger
- No autonomous research cron/daemon
- No broker/proposal/trade/journal mutation
- No external API/Grok/xAI without approval

---

## Open Risks

| Risk | Severity |
|------|----------|
| Backup schedule gap (last automated: April 21) | MEDIUM |
| Ollama GPU OOM at high num_ctx | LOW (capped at 8K) |
| Confidence scores still cluster 0.6-0.7 | LOW |

---

## Next Recommended Gate

**Phase 2A — embedding architecture pilot.**

Phase 2A is NOT approved yet. Before embeddings, require:
- Architecture review of hermes_embedding_queue → content_embeddings flow
- Rollback plan for any embedding writes
- Row cap (1-2 rows for pilot)
- No production promotion
- Explicit operator approval
