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
The identity is `SYMBOL::account::<first-exit>..<last-exit>` (lead ruling 2026-11-03: an id must bind the exit, so the
same symbol in two accounts is two cases and a later, separate exit cluster is its own case).
Fields: the exits of the cluster, `pre_exit_shares` **with its `pre_exit_source`**, `residual_shares` with its
`residual_as_of`, `pre_exit_weight_pct`, `realized_pnl`, `materiality_tier`, `residual_pct_of_pre_exit`,
`residual_note`, `gaps_json` (what could not be read and travelled with this row), `state`, `state_since`,
`eligibility_json`, `plan_json`, `last_nudge_at`, `last_p1_at`, `operator_decision`, `operator_note`, `as_of`, `source`.

Every fact that could not be read is **stored as unknown and named**, never as a zero: a missing denominator, a NULL
realized P&L, an ambiguous share count and a positions snapshot older than the exit are all gaps on the row.

## The three rules (policy-driven, one function each)

- **Residual is a displayed fact, never a silencer** (operator ruling 2026-11-03: "drop 'held' as a disqualifier… a
  residual is a FACT TO DISPLAY"). `policy.residual_display(pre_exit, residual, last_exit_date)` returns the percentage
  and a plain sentence — `"200 of 1,400 shares remain after the 2026-10-30 exit (14.3%; pre_exit_shares from the fill ledger)"` — and nothing in the engine
  decides held/not-held. Every confirmed exit cluster opens a case; a 92% residual is shown exactly like a 0.2% one.
  Pre-exit is the shares held immediately before the **final** exit (shares sold in that exit + residual), not the sum of
  every exit.
- **Materiality** — `policy.materiality_tier(realized_loss, weight_pct, policy)` → T1 / T2 / T3, or **UNKNOWN** when the
  realized loss cannot be read. UNKNOWN is page-worthy by contract: it is what "we could not read the number" means, and
  treating it as the quiet rung was the false-negative class cx-openai-2 found. The weight is a secondary signal — used
  when present, only ever raising the tier. T1 drives the P1.
- **Eligibility** — `policy.eligibility_for(account, exit_date, policy)`: a taxable exit carries the house hold
  (`taxable_hold_days`), an IRA is eligible now. The card line is `"<account>: now"` or `"<account>: <date> (<reason>)"`.

`config/recovery_policy.yaml` holds every threshold; the wash window is cross-checked at load against
`config/market_risk_policy.yaml` (`reentry_watch.wash_sale_days`) so the two files cannot fork. A missing key, an inverted
materiality ladder, `t1_never_suppressed: false`, or `residual.display_only` not true is a refusal, never a default.

Eligibility is reported, not decided: every row carries `pending_operator_decision: true` until the policy says
`eligibility.answered: true`, and the engine never recommends a re-entry. **No size, share count, stop or order value
exists in this piece** (MBI_BEHAVIOR = 0); the plan field is proposal text for pieces B and D.

## The fills consumer

`fills_consumer.read_confirmed_exits(conn, symbol, account, as_of=…)` reads, in order: `stopped_out_watch` (exit price
and realized P&L), `trade_transactions` (share counts and dates), `stop_last_known` (the stop level that fired when the
host did not place it), `positions_current` (the residual, approved reader batch 5: `qty` only) and
`positions_sync_runs` (the heartbeat that dates the snapshot — ungated, so the residual's age is known without reading
a column outside the approved scope). `consume_symbol()` opens or refreshes the case; `run()` walks every symbol ×
account with a confirmed exit and returns `complete: false` whenever a source failed or a case could not be built.
**Idempotent**: re-running over the same cluster refreshes the same row and keeps its state, decision, nudge clocks,
plan and operator note.

Reading rules, each a regression test:

- A missing or unreadable store is a stated gap — never an invented fill and never a silent zero.
- A watch row with no usable realized P&L is unknown, not a zero loss; the case's tier is UNKNOWN.
- A watch exit with no matching fill row has an unknown share count; a day with two watch exits is not attributed a
  day-level total to each.
- A fill dated after the last stop-out row means the cluster may be incomplete, and says so.
- A sell with no exit price opens no case (a placeholder price would make the R1 threshold zero).
- One damaged row is excluded and reported; it does not abort the symbol, and one bad case does not stop the pass.
- `as_of` and `since` are honoured, so a replay does not see a later exit.

## The replay gate (spec §4.1)

`tests/test_recovery_engine_a_20261103.py::test_the_spcx_replay_opens_t1_on_10_30_and_raises_exactly_one_p1` feeds the five
SPCX exits and the closes through 11-03 and asserts: one case, T1, opened from the 10-30 cluster, RECOVERING on the 11-02
close (+3.3% over the 137.19 exit), **exactly one P1**, text `"Recovery: SPCX +3.3% above your 2026-10-30 exit — next:
reclaims 151.62 20-day mean"`, eligibility `"schwab_taxable: 2026-11-29 (house hold 30 days after a taxable sale)"` flagged
pending, `last_p1_at` recorded, and the residual displayed at 14.3% with no "held" wording. PFLT's 1.15-share residual is
displayed the same way.

## Rails

Read-only against every store; no order, no broker write, no credential; no size, stop or order value is hard-coded —
the plan is proposal text (piece B/D), and execution stays with the operator. MBI_BEHAVIOR = 0. Because the plan is the
one free-form field the engine stores, `CaseStore.upsert` refuses a plan carrying an execution-shaped key (shares,
qty, size, stop, target, order, side, price, weight, …) at any depth: proposal text is stored, an instruction is not.

## Not in this piece

State transitions and R1–R5 trigger evaluation (B), T1 P1 delivery through the v008 batching module (C), the Home card and
Recovery page (D), stale-guidance hygiene (E), and the cross-piece replay ratchet (F).
