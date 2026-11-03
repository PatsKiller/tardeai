# Recovery & Re-Entry Engine — piece A (recovery_cases, fills consumer, residual rule, materiality)

Status: backend only. Piece B owns the market triggers and the state machine, C the notification path, D the Home card,
E stale-guidance hygiene, F the cross-piece replay ratchet. Nothing here notifies, renders, schedules, sizes or orders.

Spec: `persistent-state/handoffs/SPEC_RECOVERY_REENTRY_ENGINE_20261103.md` · operator directive 2026-11-03 P0.

## Why it exists

SPCX was stopped out five times — the last at −$12,770 on 2026-10-30 from a ~$140k position — and nothing ever told the
operator it was recovering. Two of the six failures live in this piece:

- a 200-share taxable residual after a position sold down from ~1,400 shares was treated as **held**, which killed the
  entire re-entry path; and
- nothing knew the loss was the largest of the year, so it got the same silent treatment as a −$672 exit.

## The row: `recovery_cases`

One row per symbol × account × exit cluster (`2026_11_03_recovery_cases.sql`, additive; `.down.sql` drops only this table).
Fields: the exits of the cluster, `pre_exit_shares`, `residual_shares`, `pre_exit_weight_pct`, `realized_pnl`,
`materiality_tier`, `residual_is_held` + the plain-English `held_reason`, `state`, `state_since`, `eligibility_json`,
`plan_json`, `last_nudge_at`, `last_p1_at`, `operator_decision`, `as_of`, `source`.

## The three rules (policy-driven, one function each)

- **Residual-aware held** — `policy.is_held(pre_exit, residual, policy)`. Held requires a known pre-exit size, residual ≥
  `residual_remaining_fraction` of it, and ≥ the absolute floor when one is set. SPCX 200 / 1,400 = 0.143 < 0.15 → not
  held; PFLT 1.15 shares → not held; an unknown pre-exit size is never held.
  Pre-exit is the shares held immediately before the **final** exit of the cluster (shares sold in that exit + residual),
  not the sum of every exit — a symbol cut down over months sells more shares than it ever held at once.
- **Materiality** — `policy.materiality_tier(realized_loss, weight_pct, policy)` → T1 / T2 / T3. T1 drives the P1.
- **Eligibility** — `policy.eligibility_for(account, exit_date, policy)`: a taxable exit carries the house hold
  (`taxable_hold_days`), an IRA is eligible now. The card line is `"<account>: now"` or `"<account>: <date> (<reason>)"`.

`config/recovery_policy.yaml` holds every threshold; the residual fraction and the wash window are **cross-checked** at
load against `config/market_risk_policy.yaml` (`reentry_watch.*`) so the two files can never fork. A missing key, an
inverted materiality ladder, or `t1_never_suppressed: false` is a refusal, never a default.

## The fills consumer

`fills_consumer.read_confirmed_exits(conn, symbol, account)` reads, in order: `stopped_out_watch` (exit price and realized
P&L), `trade_transactions` (share counts and dates), `stop_last_known` (the stop level that fired when the host did not
place it), `positions_current` (the residual). `consume_symbol()` opens or refreshes the case; `run()` walks every
symbol × account with a confirmed exit. **Idempotent**: re-running over the same cluster refreshes the same row.

A missing or unreadable store is a stated gap in the returned `gaps` list — never an invented fill and never a silent zero.

## The replay gate (spec §4.1)

`tests/test_recovery_engine_a_20261103.py::test_the_spcx_replay_opens_t1_on_10_30_and_raises_exactly_one_p1` feeds the five
SPCX exits and the closes through 11-03 and asserts: one case, T1, opened from the 10-30 cluster, RECOVERING on the 11-02
close (+3.3% over the 137.19 exit), **exactly one P1**, text `"Recovery: SPCX +3.3% above your 2026-10-30 exit — next:
reclaims 151.62 20-day mean"`, eligibility `"schwab_taxable: 2026-11-29 (house hold 30 days after a taxable sale)"`, and
`last_p1_at` recorded. PFLT's 1.15-share residual is asserted not-held.

## Rails

Read-only against every store; no order, no broker write, no credential; no size, stop or order value is hard-coded —
the plan is proposal text (piece B/D), and execution stays with the operator. MBI_BEHAVIOR = 0.

## Not in this piece

State transitions and R1–R5 trigger evaluation (B), T1 P1 delivery through the v008 batching module (C), the Home card and
Recovery page (D), stale-guidance hygiene (E), and the cross-piece replay ratchet (F).
