# Phase 53C — High-Level LLM Queue Schema Design

**Date:** 2026-06-01
**Status:** DESIGN ONLY — no tables created

## Proposed Tables

### high_llm_job_queue

| Column | Type | Description |
|--------|------|-------------|
| id | BIGSERIAL | PK |
| job_type | TEXT | thesis_review, strategy_analysis, source_quality, etc. |
| source_system | TEXT | hermes, tradeai, overnight_batch |
| requested_model | TEXT | gemma3:12b, gemma3:27b, gemma4:31b |
| urgency | REAL | 0.0–1.0 |
| portfolio_impact | REAL | 0.0–1.0 |
| evidence_gap | REAL | 0.0–1.0 |
| operator_value | REAL | 0.0–1.0 |
| staleness_days | INTEGER | |
| priority_score | REAL | Computed |
| context_tokens | INTEGER | Estimated |
| expected_runtime_sec | INTEGER | |
| deadline_utc | TIMESTAMPTZ | |
| status | TEXT | queued, running, completed, failed, skipped |
| model_used | TEXT | |
| runtime_seconds | REAL | |
| result_quality | REAL | 0.0–1.0 |
| actionable_output | BOOLEAN | |
| output_target | TEXT | |
| advisory_only | BOOLEAN DEFAULT true | |
| not_execution | BOOLEAN DEFAULT true | |
| created_at | TIMESTAMPTZ DEFAULT NOW() | |
| started_at | TIMESTAMPTZ | |
| completed_at | TIMESTAMPTZ | |
| error_message | TEXT | |

**Not created in Phase 53. Requires Phase 54 approval.**
