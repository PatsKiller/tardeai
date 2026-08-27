# R-2 — Strategy Family and Liquidity Gates

**Status:** COMPLETE

## What Changed

Router now applies three gate layers before YAML-weighted scoring:

1. **Eligibility gates** — basic data, out-of-scope source filtering, price minimum
2. **Quote eligibility** — stale quote detection, display-only provider warnings
3. **Family gates** — candidate classified into family, incompatible strategies blocked

### Family Classification

| Candidate Family | Compatible Strategy Families |
|-----------------|---------------------------|
| INTRADAY_MOMENTUM | INTRADAY_MOMENTUM, GAP_EVENT |
| GAP_EVENT | INTRADAY_MOMENTUM, GAP_EVENT, SHORT_SWING, EARNINGS_CATALYST |
| SHORT_SWING | SHORT_SWING, SPECULATIVE_GROWTH, RECOVERY_WATCH, SECTOR_ROTATION |
| EARNINGS_CATALYST | EARNINGS_CATALYST, SHORT_SWING, SPECULATIVE_GROWTH |
| DIVIDEND_CORE_COMPOUNDER | DIVIDEND_CORE_COMPOUNDER, SECTOR_ROTATION |
| UNKNOWN | All (conservative) |

## Shadow Comparison Results

| Model | Top Distribution |
|-------|-----------------|
| R-5 (weighted only) | momentum_scalp: 69, gap_and_go: 11, swing_trade: 1 |
| **R-2 (weighted + family)** | **momentum_scalp: 51, swing_trade: 25, +4 others** |

Family gating blocked 1,162 incompatible strategy evaluations.
Distribution improved — swing_trade went from 1 to 25 top matches.

## Route Audit Metadata

Each match now includes: `candidate_family`, `strategy_family`, `family_gate_blocked`,
`family_gate_reason`, `eligibility_status`, `quote_eligibility_status`.
`scoring_model_version` = `yaml_weighted_v1_family_gate_v1`.

## Tests

15/15 R-2 + R-5 15/15 + SP-2C 17/17 regression.
