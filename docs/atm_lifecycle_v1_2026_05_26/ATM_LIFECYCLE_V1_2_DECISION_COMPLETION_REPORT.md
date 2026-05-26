# ATM Lifecycle v1.2 — Decision Completion Report

**Date:** 2026-05-26  
**Commit:** `7bac5b6`  

## Safety Confirmation

| Control | Status |
|---------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| manual_kill_switch_only | true |
| ATM mode | not changed |
| Orders placed | NONE |
| Positions modified | NONE |
| Proposals expired | NONE |

## Decision Status

| Metric | Value |
|--------|-------|
| **Total overdue positions** | 10 |
| **Decisions recorded** | 9 |
| **Missing decisions** | 1 |
| **Missing stop positions with decisions** | 1 of 2 (FLYW #19 decided, GCTS #23 NOT decided) |
| **TEST_ONLY rows** | 0 |
| **Invalid decision values** | 0 |
| **Missing reason fields** | 0 |
| **Duplicate trade decisions** | FLYW #19 has 3 records (operator submitted multiple times) |
| **Lifecycle events created** | 11 (operator_review/overdue_position_decision_recorded) |

## Decision Summary

| Decision | Count | Positions |
|----------|-------|-----------|
| review_for_manual_close | 5 | GCTS #20, INFU #9, EVC #4, MNKD #2, SMX #1 |
| missing_data_verify_first | 5 | GCTS #22, FLYW #19 (x3), BLBD #16 |
| strategy_mismatch_investigate | 1 | BLBD #15 |
| keep_open | 0 | — |
| review_stop_or_trailing_adjustment | 0 | — |

## Per-Position Status

| Symbol | Trade ID | Days | Stop | Decision | Status |
|--------|----------|------|------|----------|--------|
| GCTS | #23 | 13d | MISSING | **NONE** | **UNRESOLVED** |
| GCTS | #22 | 13d | $1.42 | missing_data_verify_first | recorded |
| GCTS | #20 | 13d | $1.42 | review_for_manual_close | recorded |
| FLYW | #19 | 14d | MISSING | missing_data_verify_first | recorded |
| BLBD | #16 | 14d | $76.23 | missing_data_verify_first | recorded |
| BLBD | #15 | 14d | $76.23 | strategy_mismatch_investigate | recorded |
| INFU | #9 | 15d | $7.97 | review_for_manual_close | recorded |
| EVC | #4 | 15d | $7.71 | review_for_manual_close | recorded |
| MNKD | #2 | 19d | $3.38 | review_for_manual_close | recorded |
| SMX | #1 | 19d | $1.23 | review_for_manual_close | recorded |

## Unresolved Items

### 1. GCTS #23 — NO DECISION RECORDED

- **Symbol:** GCTS
- **Strategy:** momentum_scalp
- **Days held:** 13
- **Stop:** MISSING
- **Risk:** HIGH (missing stop + no decision)
- **Action needed:** Operator must record a decision via ATM Control Room

### 2. FLYW #19 — Duplicate Decisions

FLYW #19 has 3 decision records (all `missing_data_verify_first`). This is harmless
but indicates the operator submitted the form multiple times. The API currently allows
multiple submissions per trade. A future improvement should upsert instead of insert.

## Data Quality Notes

- All 11 decision records have valid `decision` values
- All 11 have non-empty `decision_reason` ("missing data")
- All operator_note fields are empty (operator chose not to add notes)
- 11 corresponding lifecycle_events were created successfully
- 0 TEST_ONLY rows present

## Can Stale Proposal Hygiene Begin?

**NOT YET.** GCTS #23 still has no decision. It is also the only position that is both:
- Missing a DB stop
- Missing an operator decision

This is the highest-risk unresolved item. Once GCTS #23 has a decision, the overdue
decision queue will be 10/10 complete and stale proposal hygiene can begin.

## Next Recommended Action

1. **Record decision for GCTS #23** via ATM Control Room (click Decide)
2. After that: begin stale proposal hygiene (36 safe-to-expire, 42 need review)
