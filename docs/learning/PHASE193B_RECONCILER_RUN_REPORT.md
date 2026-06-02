# PHASE 193B — Reconciler Run Report

**Run:** 2026-06-02 ~12:20 ET · `scripts/reconcile_protection_advisory_outcomes.py` · paper only

---

## Result
| Metric | Value |
|---|---|
| Trades reconciled | 31 (24 closed + 7 open with advisory) |
| final_closed | 24 |
| interim_open | 7 |
| operator **accepted** | 1 (ANY) |
| operator **ignored** | 0 |
| baseline (closed, no advisory) | 24 |
| **baseline gave back profit** | **10 → 41.7%** |
| advisory accuracy confirmed / contradicted | 0 / 0 (no closed-with-advisory trades yet) |
| MFE units flagged | 22 |

## Headline learning signal
**41.7% of legacy closed paper trades (10 of 24) gave back profit and had no protection advisory.**
This quantifies the gap that Phases 191–192 close: nearly half of completed trades reached a better
level than they exited, with nothing prompting a stop/TP review. This is the baseline the new
advisory + adjustment workflow is measured against going forward.

## ANY (interim_open — the round-tripped case)
| Field | Value |
|---|---|
| advisory_existed | true (URGENT_PROTECTION_REVIEW) |
| adjustment_action | MOVE_STOP_TO_PROFIT_LOCK |
| stop_before → after | 3.07 → 3.56 |
| operator_decision | **accepted** |
| profit_locked_by_adjustment | $201 |
| **giveback_avoided** | **$300** |
| advisory_accuracy | in_flight (final accuracy on close) |

ANY is the first full round-trip: advisory → proposal → operator approval → applied → tracked. Its
final accuracy will be scored when it closes.

## Forward behavior
- As ANY/SNOW and future advised trades close, `final_closed` records gain real `confirmed` /
  `contradicted` accuracy, `profit_left_on_table`, and `take_profit_would_have_helped` /
  `trailing_would_have_helped`.
- The reconciler is idempotent (upsert by trade_id) — recommended cron: post-close hook + nightly.

## Data-integrity follow-up
`mfe_units_validated=false` on 22 rows — `max_favorable_excursion` is unit-inconsistent in the
source. Flagged for a pipeline fix; the reconciler does not fabricate dollar give-back from it.
