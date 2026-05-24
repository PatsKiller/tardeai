# SP-2B Scope — Route Audit Backfill and Strategy Assignment Repair

## Purpose

SP-2 found 74/83 proposals (89%) missing route audit. SP-2B investigates root cause,
backfills route audit evidence for existing proposals, and adds readiness blockers
for missing route audit and invalid strategy assignments.

## SP-2 Findings

- 74/83 proposals missing strategy_setup_matches records
- 6 proposals use strategy_id='screener' (not a valid YAML strategy)
- 9 proposals have YAML/DB config hash drift
- 13 YAML strategies never selected for any proposal

## Root Cause

Neither auto_proposal_generator.py nor incubator_proposal_promoter.py calls
multi_setup_router.store_setup_matches() during proposal creation. The route audit
function exists but is only available in manual --pending-proposals mode.

## What SP-2B Can Do

- Document root cause
- Backfill route audit evidence using multi_setup_router for existing proposals
- Report invalid strategy assignments
- Report YAML/DB config drift
- Add readiness blockers for missing route audit and invalid strategy_id
- Design fix for proposal creation pipeline (SP-2C)

## What SP-2B Must Not Change

- Strategy activation
- YAML thresholds
- Finviz screeners
- Proposal strategy_id (original assignment preserved)
- Trade creation / order submission
- Approval gate logic (only adds blockers, never removes)
- Phase 6/7/8 behavior

## Backfill Policy

- Backfill inserts into strategy_setup_matches only
- Records marked backfill_source='SP-2B'
- Idempotent by proposal_id + strategy_id
- Original proposal strategy_id is NEVER changed
- Mismatch between backfill best-match and original assignment is flagged, not auto-fixed

## Invalid Strategy Policy

- strategy_id='screener' is flagged as invalid (not YAML-backed)
- Proposals with invalid strategy_id get a readiness blocker
- No auto-reassignment

## Human-Review-Only

All recommendations are human_review_only. Fixing the creation pipeline (SP-2C)
requires separate operator approval.
