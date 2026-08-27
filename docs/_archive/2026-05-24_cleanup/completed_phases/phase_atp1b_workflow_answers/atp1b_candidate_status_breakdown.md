# Candidate Status Breakdown Report
Generated: 2026-05-20T01:13:44.994964+00:00

## Universe Strategy Fit Audit (run: arch4_20260519_203108)

### Recommendation Totals

| Recommendation | Count |
|----------------|-------|
| no_fit | 619 |
| blocked_by_strategy_fit | 331 |
| watchpool_candidate | 316 |
| proposal_candidate_pending_gates | 39 |

### no_fit — by Strategy Family

| Strategy Family | Count |
|-----------------|-------|
| SHORT_SWING | 582 |
| MEDIUM_SWING | 18 |
| CASH | 16 |
| INTRADAY | 3 |

### no_fit — by Match Strength

| Match Strength | Count |
|----------------|-------|
| NO_MATCH | 619 |

### blocked_by_strategy_fit — by Family Gate Status

| Family Gate | Count |
|-------------|-------|
| FAIL | 327 |
| PASS | 4 |

### blocked_by_strategy_fit — by Liquidity Gate Status

| Liquidity Gate | Count |
|----------------|-------|
| PASS | 331 |

### watchpool_candidate — by Strategy ID

| Strategy ID | Count |
|-------------|-------|
| swing_trade | 158 |
| recovery_watch | 88 |
| momentum_scalp | 56 |
| cash_or_stable | 11 |
| earnings_pre_buildup | 3 |

### proposal_candidate_pending_gates — by Strategy ID

| Strategy ID | Count |
|-------------|-------|
| swing_trade | 28 |
| momentum_scalp | 10 |
| gap_and_go | 1 |

## Afterhours Candidate Snapshot (snapshot: afterhours_2026-05-19_after_close)

### Readiness Status Totals

| Readiness Status | Count |
|------------------|-------|
| needs_data | 619 |
| blocked_by_strategy_fit | 331 |
| watchpool_candidate | 186 |
| no_fit | 136 |
| ready_for_review | 39 |

### Readiness by Quote Status

| Readiness Status | Quote Status | Count |
|------------------|--------------|-------|
| blocked_by_strategy_fit | fresh | 331 |
| needs_data | fresh | 619 |
| no_fit | fresh | 130 |
| no_fit | stale | 6 |
| ready_for_review | fresh | 39 |
| watchpool_candidate | fresh | 186 |

### Readiness by Top Strategy

| Readiness Status | Top Strategy | Count |
|------------------|--------------|-------|
| blocked_by_strategy_fit | earnings_pre_buildup | 250 |
| blocked_by_strategy_fit | fib_retracement_bounce | 3 |
| blocked_by_strategy_fit | momentum_scalp | 6 |
| blocked_by_strategy_fit | recovery_watch | 14 |
| blocked_by_strategy_fit | swing_trade | 58 |
| needs_data | cash_or_stable | 16 |
| needs_data | earnings_pre_buildup | 582 |
| needs_data | momentum_scalp | 3 |
| needs_data | recovery_watch | 18 |
| no_fit | NULL | 6 |
| no_fit | cash_or_stable | 11 |
| no_fit | earnings_pre_buildup | 3 |
| no_fit | momentum_scalp | 29 |
| no_fit | recovery_watch | 87 |
| ready_for_review | gap_and_go | 1 |
| ready_for_review | momentum_scalp | 10 |
| ready_for_review | swing_trade | 28 |
| watchpool_candidate | momentum_scalp | 27 |
| watchpool_candidate | recovery_watch | 1 |
| watchpool_candidate | swing_trade | 158 |
