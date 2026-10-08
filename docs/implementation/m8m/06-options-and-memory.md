# 06 — Options and memory

Read-only SQL as role `trade_ai`. No broker route, no order, no 2FA, no gate edit. Counts are not eligibility.

## Options

| Table | Count | Clock used | Max |
|---|---:|---|---|
| `public.options_chain_snapshots` | 48374 | `captured_at` | 2026-10-06 08:12:03-04:00 |
| `public.option_chain_snapshots` | 1601 | `as_of` | 2026-10-06 |
| `public.options_approval_queue` | 2936 | `reviewed_at` | 2026-09-26 14:57:36-04:00 |
| `public.options_monitored_positions` | 1 | `expiration` | 2026-09-18 |
| `public.options_monitored_alerts` | 1443 | not selected | |
| `public.options_lifecycle_outcomes` | 0 | | |
| `public.options_lifecycle_decisions` | 0 | | |
| `public.options_lifecycle_tickets` | 0 | | |
| `public.options_fill_evidence` | 0 | | |
| `public.options_journal_events` | 0 | | |

Chain capture on this calendar day is real. The lifecycle outcome side of the funnel has a zero denominator. That is **NOT_MEASURED** as a completed desk, and D-OPT-001 records the gap. `expiration` on the single monitored row is not a freshness clock. Approval review has not moved past 2026-09-26 on the column that was read.

#1460 (positions source of truth, AGENTS 1.4.0) is the freeze pin. This pass did not add a writer.

`/api/v2/health` on this pin is `healthy` / score 86 / mode `advisory`. That score is not an options eligibility stamp.

## Memory and wakes

| Table | Count | Clock | Max |
|---|---:|---|---|
| `public.agent_wake_receipts` | 125 | `observed_at` | 2026-09-07 12:29:22-04:00 |
| `public.persistent_agent_wakes` | 24 | `window_start` | 2026-09-07 12:00:00-04:00 |
| `public.hermes_memory_events` | 13248 | not selected | |
| `public.trade_lesson_memory` | 282 | `close_date` | 2026-10-05 |
| `public.strategy_lesson_rollup` | 997 | `period_start` | 2026-09-06 |
| `public.inference_memory` | 91 | not selected | |
| `intelligence.memory_context` | 0 | | RLS may hide rows |
| `memory_r10_m2.memory_fact_version` | 0 | | FORCE RLS |
| `memory_r10_m2.memory_identity` | 0 | | FORCE RLS |

A lesson row dated 2026-10-05 does not show that a later judgment changed. Wake receipts stop on 2026-09-07 (D-MEM-001). M1–M5 and the 12 gates were **not** recomputed. Memory behavior influence was not turned on. No live wake was started.

`public.communication_outbox` count 72680, max `created_at` 2026-10-06 11:13:03-04:00. `public.telegram_outbox` count 8158. Neither count is a delivery receipt.

## Advisory shadow

`tradeai-advisory-shadow-session.service` failed at 09:23 ET with exit code 1. The appended log's last sessions show `pass=False`, `live=False`, `spend=$0.0`, `progress=40/20`. One earlier line in the same tail says `pass=True`. The false result is not yet a root-caused code defect. It is a failed oneshot on a unit whose working directory is the rebuild tree, not the freeze pin.
