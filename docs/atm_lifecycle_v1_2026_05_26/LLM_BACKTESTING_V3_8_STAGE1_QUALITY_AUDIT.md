# v3.8 Stage 1 Close-Analysis Quality Audit

**Date:** 2026-05-28

## Row Count: 4

## Per-Row Quality

| ID | Symbol | Status | Summary | Thesis | Execution | Stop | TCA | Lessons | Confidence | Output | Hash | Classification |
|----|--------|--------|---------|--------|-----------|------|-----|---------|------------|--------|------|---------------|
| 1 | APPS #34 | dry_run | YES | NO | NO | NO | NO | NO | NO | NO | YES | **partial_review** |
| 2 | NVDA #29 | dry_run | YES | NO | NO | NO | NO | NO | NO | NO | YES | **partial_review** |
| 3 | INFU #21 | dry_run | YES | NO | NO | NO | NO | NO | NO | NO | YES | **partial_review** |
| 4 | BLBD #15 | dry_run | YES | NO | NO | NO | NO | NO | NO | NO | YES | **partial_review** |

## What Exists
- `summary`: Human-written one-liner describing the trade outcome
- `input_snapshot_hash`: Deterministic hash of the trade input data
- `model_name`, `prompt_version`, `model_provider`: Correctly recorded

## What Is Missing
- `thesis_assessment`, `execution_assessment`, `stop_assessment`, `tca_assessment`: All NULL
- `lessons`, `confidence`, `data_quality_gaps`: All NULL
- `output_payload`: NULL (model returned empty response)
- `error_message`: NULL (model didn't error, just returned empty)

## Root Cause
The local LLM (qwen3:14b) was called with `fallback=False` but returned an empty response.
The review rows were then created manually with operator summaries but without structured
model output. The prompt may need adjustment for the local model's expected input format.

## Stage 2 Readiness

**PARTIALLY READY.** Stage 2 delayed review can use these rows as Stage 1 references
because they contain the trade identity, input hash, and human summary. However, Stage 2
would ideally compare against structured model assessments, not just one-line summaries.

**Recommended action:** Proceed to v3.9 with current partial reviews as a baseline.
When the local LLM prompt/parser is improved, rerun Stage 1 with `--apply` to upgrade
these rows with full structured output. Stage 2 can then compare old vs new assessments.

## Safety
- No orders placed / No broker writes / No paper_trades changes
- No journal/backtest mutations / No cron / No Grok
- ALPACA_MODE=paper, LLM_DISABLE=true
