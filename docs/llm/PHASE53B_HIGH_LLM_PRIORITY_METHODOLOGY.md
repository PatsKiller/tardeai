# Phase 53B — High-Level LLM Priority Methodology

**Date:** 2026-06-01
**Status:** COMPLETE — design only

## Priority Formula

```
priority_score =
    3.0 * urgency
  + 2.5 * portfolio_impact
  + 2.0 * evidence_gap_score
  + 1.5 * operator_value
  + 1.0 * staleness_age_boost
  + 1.0 * deadline_pressure
  - 2.0 * duplicate_penalty
  - 1.5 * low_quality_penalty
  - 1.0 * retry_penalty
```

All factors normalized 0.0–1.0.

## Quota Policy

| Pool | Share | Examples |
|------|-------|---------|
| Journal/backtest learning | 20% | Thesis reviews, strategy analysis |
| Portfolio/tax/income risk | 20% | Income gap, tax lot, retirement |
| Hermes research quality | 20% | Librarian, backlog, source quality |
| Flex pool (aging/operator) | 20% | Old jobs aging up, operator priority |
| Legacy overnight batch | 20% | Existing deep queue jobs |

No pool may exceed 40% unless others are empty.

## Aging Policy

- Jobs age +0.1 priority/day after initial submission
- Max age boost: 3.0 (after 30 days)

## Market-Hours Restrictions

- Fast model (gemma3:4b) preferred during 09:30–16:00 ET
- High model (gemma3:12b+) preferred 20:00–08:00 ET and weekends
- Emergency override available via operator flag

## Kill Switch

- File: `data/state/HIGH_LLM_SCHEDULER_DISABLED`
- Effect: all queued jobs skip, fall back to direct Ollama calls

## Telemetry

Each completed job must record: job_id, model_used, runtime_seconds, tokens, result_quality, actionable_output (bool).
