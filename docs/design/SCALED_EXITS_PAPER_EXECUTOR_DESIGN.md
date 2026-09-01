# Scaled Exits for the Paper Executor — Design Spec (SX)

Status:      ACTIVE
as_of:       2026-06-12T18:06:36-04:00
Measured at: efcc51365 / not measured

**Status: DESIGN ONLY — no implementation authorized by this document.**
**Date: 2026-06-12 · Owner: operator · Scope: Alpaca PAPER pipeline only. Schwab is explicitly out of scope (no write path exists; see ENGINEERING_HARD_RULES).**

## 1. Problem

Entry plans now carry a layered exit ladder (T1 +1R / T2 plan target / T3 Street-mean runner —
`watchlist_entry_planner._exit_ladder`, mirrored in `command-center-v3 lib/exitLadder.ts`), but the
paper executor still exits all-or-nothing: one Alpaca **bracket** = one entry + ONE take-profit +
ONE stop (`proposal_paper_submitter.dry_run_bracket`, `order_class=bracket`). A trade that tags T1
and reverses gives back everything; a trade that runs to the Street mean is capped at target1.

What already exists and must NOT be duplicated:
- **Stop side of the ladder is live**: `paper_trade_monitor` R-multiple trailing (breakeven at
  1R/1.5R per strategy family via `strategy_trailing_policy`, lock 2R at 3R) under the
  STOP-V2.2 `unified_stop_supervisor` (3-min cycle, reconcile-first).
- **Profit side is missing**: no partial scale-out exists anywhere in the executor.

## 2. Broker constraint (drives the whole design)

Alpaca bracket orders bind the FULL qty to one TP leg + one SL leg. Shares can only be committed
to one open sell order at a time, so "one bracket + extra limit sells" is rejected, and partial
sells outside a bracket require canceling/shrinking the bracket legs first (racy: a stop-out during
the cancel-replace window leaves naked shares).

### Options considered

| | A. Tranche brackets (split at entry) | B. Single bracket + supervisor partial sells | C. Plain entry + supervisor-owned exit basket |
|---|---|---|---|
| Mechanics | Split qty into 2–3 sibling brackets: same entry limit + same initial stop, different TPs (T1/T2/T3) | Today's bracket; on T1 touch, supervisor cancels/shrinks legs, sells ⅓, re-arms | Entry only; on fill, supervisor places stop + ladder limits |
| Protection | Broker-held at all times (per tranche) | Naked-share window on every scale | Naked window between fill and basket placement |
| New write surface | None in-trade (entry-time only) | Cancel/replace/partial-sell in-trade | Full exit management in-trade |
| Fits Phase 189 "broker stops must exist" | ✅ | ❌ (windows) | ❌ (windows) |

**Decision: Option A — tranche brackets.** No in-trade naked windows, no new mutation surface
beyond what STOP-V2 already reconciles, and the existing R-trailing supervisor keeps working per
tranche unchanged.

## 3. Design

### 3.1 Tranche construction (entry time, `proposal_paper_submitter`)

- Ladder source: proposal's stored `exit_ladder` (from `watchlist_entry_plans.plan` via the
  proposals-scope planner run), else computed at submit time with the same `_exit_ladder` math —
  one shared function, never re-derived ad hoc.
- Split `proposed_shares` into tranches by config weights (default `[0.4, 0.3, 0.3]` →
  T1/T2/T3). All weights/thresholds from config — **no hardcoded values** (hard rule).
- Each tranche = its own bracket: same limit entry, same initial stop, TP = its ladder rung.
- `client_order_id` lineage: `<base>-L1|-L2|-L3`, plus `ladder_group_id = <base>` persisted on
  each `paper_trades` row. The group is ONE position for max-positions/risk caps, not three.
- **Min-ladder guard**: if `shares < scaled_exits.min_shares` (config, e.g. 30) or any tranche
  rounds to 0, fall back to today's single bracket and log `LADDER_SKIPPED_MIN_QTY`.

### 3.2 Gates (extends the existing 14 blocker checks; never bypasses them)

New blockers, applied per group before any tranche submits:
- `LADDER_NOT_MONOTONIC`: not stop < entry < T1 < T2 (< T3).
- `LADDER_T1_BELOW_1R`: T1 < entry + 1R (degenerate ladder).
- `LADDER_QTY_MISMATCH`: tranche qtys don't sum to proposed shares.
- All-or-nothing submit: tranches submit sequentially; on any rejection, cancel already-accepted
  sibling tranches and mark the group `LADDER_PARTIAL_ABORT` (no orphan tranches).

### 3.3 In-trade behavior (STOP-V2 harmony — no new mover)

- R-multiple trailing already moves stops to breakeven at ~1R: **T1's TP fill and the trailing
  breakeven move are the same event economically**. No ladder-specific stop mover is added in
  SX-1; `strategy_trailing_policy` continues to govern all three tranches independently.
- SX-2 (later, optional): ladder-event awareness — when tranche L1's TP fills, immediately
  re-anchor siblings' trail tier (breakeven floor) instead of waiting for the next R threshold.
  Implemented inside the existing supervisor cycle, reconcile-first, never outside it.
- News auto-close, time stops, phantom/integrity checks: unchanged, applied per tranche; group
  rollup in reporting only.

### 3.4 Recon / verification / journal

- `trade_fill_verifier`, `sync_positions`, `detect_closed_positions`: match per tranche by
  client_order_id; add group rollup view keyed on `ladder_group_id`.
- Journal: one trade-group entry with per-tranche legs; P&L, R and expectancy computed at GROUP
  level (a group is one decision). Win-rate stats must not count 3 tranches as 3 trades —
  P-level trade counting (36/2000) counts groups.
- Telegram fill alerts: per tranche, prefixed `L1/L2/L3 of <group>`.

### 3.5 Schema

- `paper_trade_proposals`: + `exit_ladder jsonb` (nullable; populated at proposal creation from
  the planner or at approve time).
- `paper_trades`: + `ladder_group_id text`, + `tranche_label text` (`L1|L2|L3|SINGLE`).
- Backfill: existing rows get `tranche_label='SINGLE'`, group = own client_order_id.

## 4. Rollout phases (prop-desk lifecycle gates)

| Phase | What | Gate to advance |
|---|---|---|
| **SX-0 shadow** | Proposals store `exit_ladder`; executor logs the WOULD-BE tranche plan (audit event `LADDER_SHADOW`) but submits today's single bracket. Forward-measure: how often T1/T2/T3 would have filled vs the single target. | ≥ 50 shadowed round-trips; shadow shows laddered expectancy ≥ single-target expectancy on the same trades |
| **SX-1 paper tranches** | `scaled_exits.enabled=true` (config, default **false** = kill switch): tranche brackets live on paper. | 11+3 gates green; validator suite green; 2 weeks clean recon (no orphan tranches, no qty drift) |
| **SX-2 ladder-aware trailing** | Sibling re-anchor on T1 fill inside unified_stop_supervisor. | SX-1 stable; stop-change audit shows zero naked windows |
| **SX-3 evaluation** | A/B expectancy laddered vs single-target after ≥ 50 laddered groups; promote or retire **by expectancy, not win-rate** (open gate-roadmap decision applies). | Operator review |

## 5. Safety invariants (unchanged, restated)

- Paper only: `ALPACA_MODE=paper`, `live_trading_allowed=False`, paper endpoint asserts — all
  existing hard blockers stay in front of every tranche submit.
- **No Schwab writes, ever, in this design.** Schwab remains read-only observe + Manual ToS
  drafts; the ladder reaches Schwab accounts only as advisory text on tickets the operator types
  into Thinkorswim. `validate_schwab_no_writes.py` must stay 18/18 through every SX phase.
- Kill switch: `scaled_exits.enabled=false` reverts to single brackets instantly; open tranche
  groups are left to run to completion (no forced unwind).

## 6. Open questions (resolve before SX-1)

1. Stop-move mechanics on Alpaca for bracket legs (replace vs cancel+create) — confirm the
   current trailing implementation's atomicity holds per tranche under 3 sibling brackets.
2. Partial entry fills on DAY limits: a tranche that doesn't fill by EOD cancels with its legs —
   accept (log `LADDER_TRANCHE_UNFILLED`) or re-arm next session? Proposed: accept + log.
3. Odd lots: rounding remainder goes to L1 (the de-risk tranche) — confirm.
4. Does Alpaca paper accept 3 same-symbol same-side brackets concurrently? Verify in SX-0 with a
   manual paper test before building SX-1.
