# Hermes Phase 30A — Expanded Librarian Dry-Run Design

**Date:** 2026-06-01
**Status:** COMPLETE

---

## Purpose

Run the Hermes Librarian against the 4 newly visible Trade AI surfaces to identify research gaps that should become Research Backlog items.

## Views Used

| View | Rows | Checks |
|------|------|--------|
| hermes_v_journal_learning_context | 0 | JRN-1 through JRN-6 (will report empty) |
| hermes_v_backtest_results_context | 40 | BT-1 through BT-6 |
| hermes_v_screener_context | 211 | MS-1 through MS-4 |
| hermes_v_catalyst_quality_context | 345 | CAT-1 through CAT-3 |

## Checks

### Journal (JRN) — requires hermes_v_journal_learning_context

| ID | Check | Trigger |
|----|-------|---------|
| JRN-1 | Stale trade thesis | Thesis review >90 days old |
| JRN-2 | Missing exit lesson | Closed trade with no thesis review |
| JRN-3 | Missing catalyst at entry | Trade without catalyst in ±24h |
| JRN-4 | Weak catalyst at entry | Catalyst grade WEAK_GENERIC or STALE |
| JRN-5 | Journal note too vague | Learning digest item lacks specific lesson |
| JRN-6 | Case study missing actionability | Thesis review lacks next-trade guidance |

*Note: Journal view has 0 rows — all JRN checks will report "no data available"*

### Backtest (BT) — requires hermes_v_backtest_results_context

| ID | Check | Trigger |
|----|-------|---------|
| BT-1 | Backtest contradiction | win_rate < 40% with sample_size >= 5 |
| BT-2 | Failed setup pattern | Same strategy fails repeatedly |
| BT-3 | Strategy underperformance | profit_factor < 1.0 with sample_size >= 10 |
| BT-4 | Insufficient sample | confidence_level = INSUFFICIENT |
| BT-5 | Zero win rate | win_rate = 0 |

### Screener (MS) — requires hermes_v_screener_context

| ID | Check | Trigger |
|----|-------|---------|
| MS-1 | Underfilled run | status = RUN_UNDERFILLED |
| MS-2 | Low GO ratio | go_count / (go_count + wait_count + no_go_count) < 0.01 |
| MS-3 | No GO candidates | go_count = 0 |

### Catalyst (CAT) — requires hermes_v_catalyst_quality_context

| ID | Check | Trigger |
|----|-------|---------|
| CAT-1 | Low confidence catalyst | confidence < 0.4 |
| CAT-2 | Generic catalyst type | catalyst_type = 'other' |
| CAT-3 | Low impact catalyst | impact_score < 3.0 AND severity = 'low' |

## Caps

- Max rows reviewed per view: 25
- Max total findings: 25
- Max backlog candidates: 10
- DB writes: ZERO
