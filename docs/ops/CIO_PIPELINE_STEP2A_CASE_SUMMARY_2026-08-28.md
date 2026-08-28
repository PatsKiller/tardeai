# CIO Pipeline Step 2A — CASE_SUMMARY from attached VALID research

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MEMORY_BEHAVIOR_INFLUENCE: 0
Promotion ceiling: REVIEW_READY

## What this slice did

Step 1 joined `hermes_result_id` onto 321 open plans. Memory still had **CASE_SUMMARY = 0 producers**. Lane looked starved because nothing emitted an ACTIVE-eligible class (P8.1). RESEARCH_REFERENCE remains CANDIDATE by design.

This PR mints `MemoryRecord@v1` `CASE_SUMMARY` from plans that already have a joined VALID/PARTIAL Hermes result, via `build_memory_record` + `admit_candidate` + durable JSONL. Provenance is plan_id + research_id + hermes_result_id. Subject is `research_case:{SYMBOL}` (never a price/holding/cash/stop field). Idempotent on (plan_id, hermes_result_id). Fail-soft on the Hermes complete path.

## What this slice did not do

- No action / ThesisDecisionGate change. Research still cannot promote an order.
- No Telegram / situation notify.
- No AGENT_COMMITMENT producer.
- No research backfill `--apply` on the 474 plans still missing `hermes_result_id`.
- Stop-management / quote freshness / reentry books / cio_run_worker LLM: untouched.
- ADMIT_ACTIVE_TYPES unchanged. RESEARCH_REFERENCE still CANDIDATE.

## Before (CURRENT `671d760f`, production durable reader)

| Metric | Value |
|---|---|
| durable memories | 444 |
| RESEARCH_REFERENCE | 441 |
| CASE_SUMMARY | **0** |
| AGENT_COMMITMENT | 0 |
| plans_with_hermes_result_id | 321 |

## After (fill at promote)

| Metric | After promote |
|---|---|
| SOURCE / health | *(filled live)* |
| CASE_SUMMARY | *(must be > 0)* |
| sample memory_ids | *(5)* |
| plans_with_hermes_result_id | still ≥ 321 |
| RESEARCH_REFERENCE | still dominant is OK |
| new Telegram from this producer | none |

## Hook / backfill

- Forward: `on_hermes_completed` after `result_joined`.
- CLI: `scripts/cio_case_summary_backfill.py` (dry-run default; `--apply` to write). Source = open plans **with** `hermes_result_id` only.

## Step 2B (not this PR)

New-name surfacing, or an AGENT_COMMITMENT producer. Not notify. Not gate loosening.
