# Hermes Phase 1H — Prompt Hardening + Limited Ingestion Report

**Date:** 2026-05-30
**Status:** COMPLETE — 3/3 tasks staged, all hardened validations pass

---

## Part A: Prompt & Validator Hardening

### Phase 1G Findings Addressed

| Finding | Fix |
|---------|-----|
| Challenge_points are questions not findings | Prompt: "State FINDINGS, not questions. BAD: 'Analyze...' GOOD: 'Strategy was mismatched because...'" |
| Trade reflections lack context | Prompt: requires facts/inferences separation, missing_data checklist |
| System tasks fail validation | Prompt: explicit example output schema with metric extraction |
| Confidence always 0.6 | Prompt: requires confidence_explanation |
| Weak evidence depth | Validator: rejects < 2 substantive evidence keys |
| No external claim detection | Validator: rejects "according to latest web", "live market", etc. |

### New Files

| File | Purpose |
|------|---------|
| `scripts/hermes_research_prompt.py` | Centralized hardened prompt builder |
| Updated `scripts/hermes_staging_ingest.py` | Hardened validator with 7 new checks |

### Validator Improvements

| Check | Type |
|-------|------|
| Evidence depth (≥ 2 substantive keys) | NEW |
| Limitations required non-empty | NEW |
| High confidence (> 0.85) requires ≥ 3 evidence refs | NEW |
| Question-style challenge_points rejected | NEW |
| External unsupported claims rejected | NEW |
| Source_views required non-empty | NEW |
| Credential pattern detection | NEW |
| Expanded forbidden keywords (buy now, sell now, etc.) | UPDATED |

### Tests: 9/9 PASS

| Test | Result |
|------|--------|
| Valid staged payload | PASS |
| Missing evidence | REJECTED (correct) |
| Missing limitations | REJECTED (correct) |
| High confidence + weak evidence | REJECTED (correct) |
| Execution language ("buy now") | REJECTED (correct) |
| External claim ("latest web") | REJECTED (correct) |
| Invalid source | REJECTED (correct) |
| Question-style challenge_points | REJECTED (correct) |
| Missing source_views | REJECTED (correct) |

---

## Part B: Limited Staged Ingestion

### Tasks

| # | Task ID | Type | Symbol | Status | Confidence | Row ID |
|---|---------|------|--------|--------|------------|--------|
| 1 | phase1h_task_01 | ticker_thesis_challenge | INFU | STAGED | 0.7 | 5 |
| 2 | phase1h_task_02 | trade_reflection | ASPN | STAGED | 0.6 | 6 |
| 3 | phase1h_task_03 | pipeline_quality_validation | — | STAGED | 0.6 | 7 |

**3/3 tasks validated and staged. 0 rejected.**

### Quality Comparison vs Phase 1F

| Metric | Phase 1F | Phase 1H | Improvement |
|--------|----------|----------|-------------|
| Tasks attempted | 5 | 3 | — |
| Tasks validated | 3 (60%) | **3 (100%)** | +40% |
| Pipeline task success | 0/2 (0%) | **1/1 (100%)** | Fixed |
| Challenge_points as findings | Mixed | **All findings** | Hardening worked |
| Confidence variation | All 0.6 | 0.6–0.7 | Slightly better |

---

## Row Counts Before/After

| Table | Before | After | Change |
|-------|--------|-------|--------|
| hermes_research_intelligence | 4 | **7** | +3 |
| hermes_memory_events | 1 | 1 | 0 |
| All others | 0 | 0 | 0 |

## Safety

| Item | Status |
|------|--------|
| Production writes | **ZERO** |
| content_embeddings | **ZERO** |
| Broker access | **ZERO** |
| Proposal mutations | **ZERO** |
| paper_trades | **ZERO** (38 unchanged) |
| Journal | **ZERO** |
| Cron/service/daemon | **ZERO** |
| External APIs | **ZERO** |

## Next Recommended Gate

**Phase 2A — embedding architecture pilot.** Evidence quality is now strong enough for limited RAG integration testing. Requires separate approval.
