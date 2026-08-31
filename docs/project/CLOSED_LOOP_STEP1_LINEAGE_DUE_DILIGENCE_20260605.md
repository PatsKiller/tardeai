# Closed-Loop Step 1 — Execution Lineage Due Diligence (2026-06-05)

Status:      ACTIVE
as_of:       2026-06-05T22:02:42-04:00
Measured at: efcc51365 / not measured

## Broken join (from certification audit)
`paper_trades.signal_id / source_signal_id = 0%` — signal/card identity lost at execution.

## Submit paths that create paper_trades
- `scripts/paper_trade_logger.py`:
  - `approve_proposal()` (line ~1277) → INSERT (line ~1363): **MAIN** proposal→paper_trade path
    (called by the ATM auto-approver and manual approval). `prop` (full proposal row) is in scope.
  - trade-plan path (line ~256): older direct-from-plan insert.
- `scripts/alpaca_paper_adapter.py`:
  - `submit_entry()` (line ~690): broker submit insert (has `proposal_id`).
  - `sync_positions()` (line ~229): broker reconciliation insert (no proposal → lineage missing).

## Where identity lives vs is lost
- Proposal (`paper_trade_proposals`) carries: `source_signal_id` (44%), `source_strategy_card_id`,
  `primary_strategy_id`, `source_record_id`/`discovery_source` (candidate), and account routing
  (`target_account`/`final_account`/`proposed_account`).
- The INSERT into paper_trades copies `proposal_id`, `strategy_id`, `account`, `signal_grade` — but NOT
  `source_signal_id`, `source_strategy_card_id`, `signal_id`, candidate id, or execution broker/env.
- paper_trades ALREADY has columns: signal_id, source_signal_id, source_strategy_card_id, proposal_id,
  account, broker, target_account (unstamped). Account→broker/env is resolvable via the broker/account
  model (`broker_accounts`), so lineage is broker/account-neutral (not Alpaca-hardwired).

## Proposed additive schema (paper_trades) — new columns only
candidate_id, source_proposal_id, execution_account, execution_broker, execution_environment,
lineage_source, lineage_stamped_at, lineage_confidence, lineage_notes (JSONB). Existing signal/card/
proposal columns reused. All ADD COLUMN IF NOT EXISTS → additive + reversible.

## Plan
helper `trade_lineage.extract_lineage_from_proposal()` (account→broker/env via broker_accounts, neutral)
→ stamp at all submit paths → exact-proposal_id backfill for existing trades. Generic cross-broker
execution table = Phase 2 (not built here).
