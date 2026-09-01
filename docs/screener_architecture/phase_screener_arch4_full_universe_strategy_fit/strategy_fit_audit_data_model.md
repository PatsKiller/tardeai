# SCREENER-ARCH-4 — Strategy-Fit Audit Data Model

Status:      HISTORICAL
as_of:       2026-05-19T16:51:15-04:00
Measured at: efcc51365 / not measured

## Table: universe_strategy_fit_audit

| Column | Type | Purpose |
|--------|------|---------|
| id | SERIAL PK | Auto-increment |
| audit_run_id | VARCHAR(64) | Groups evaluations from one run |
| symbol | VARCHAR(10) | Ticker symbol |
| strategy_id | VARCHAR(64) | Strategy evaluated |
| strategy_family | VARCHAR(32) | INTRADAY/SHORT_SWING/MEDIUM_SWING/POSITION |
| evaluated_at | TIMESTAMPTZ | When evaluated |
| quote_status | VARCHAR(20) | fresh/stale/missing |
| liquidity_gate_status | VARCHAR(20) | PASS/FAIL/MISSING_DATA |
| family_gate_status | VARCHAR(20) | PASS/FAIL |
| required_data_status | VARCHAR(20) | COMPLETE/PARTIAL/MISSING |
| missing_fields | TEXT | JSON list of missing data fields |
| scoring_weights_used | BOOLEAN | Whether YAML scoring_weights were applied |
| raw_score | INTEGER | Raw weighted score from router |
| normalized_score | INTEGER | 0-100 normalized score |
| match_strength | VARCHAR(20) | STRONG/MODERATE/WEAK/NO_MATCH/MISSING_DATA/BLOCKED |
| criteria_met | TEXT | JSON list of criteria passed |
| criteria_failed | TEXT | JSON list of criteria failed |
| blockers | TEXT | JSON list of blockers (disqualifiers) |
| top_match_for_symbol | BOOLEAN | Best strategy for this symbol |
| recommendation | VARCHAR(40) | no_fit/needs_data/watchpool_candidate/etc |
| human_review_only | BOOLEAN | Always TRUE |
| created_at | TIMESTAMPTZ | Record creation time |

## Unique Constraint

`(audit_run_id, symbol, strategy_id)` — idempotent by run

## Rules

- Append-only audit rows
- No proposal creation
- No trade/order mutation
- No strategy activation changes
- human_review_only always TRUE
