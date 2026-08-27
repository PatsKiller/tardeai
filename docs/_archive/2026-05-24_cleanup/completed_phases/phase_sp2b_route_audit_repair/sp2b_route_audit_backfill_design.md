# SP-2B Route Audit Backfill Design

## Process

1. Load all pending + recent proposals missing strategy_setup_matches
2. For each, load ticker characteristics from trade_ai_scans and incubator_universe
3. Load all YAML strategy configs via strategy_config_loader
4. Call multi_setup_router.route_symbol() to evaluate all strategies
5. Call store_setup_matches() with proposal_id and backfill_source='SP-2B'
6. Compare backfill primary strategy with original proposal strategy_id
7. Flag mismatches as human_review_only

## Idempotency

- Check: SELECT count(*) FROM strategy_setup_matches WHERE proposal_id = X
- Skip if records already exist (original or prior backfill)
- Backfill records tagged with run_label containing 'SP-2B-backfill'

## What Is NOT Changed

- paper_trade_proposals.strategy_id — NEVER modified
- paper_trade_proposals.primary_strategy_id — NOT modified
- Approval state — NOT modified
- Trades — NOT modified
- Orders — NOT submitted

## Mismatch Handling

If backfill best-match differs from original strategy_id:
- Record the mismatch
- Log it in the report
- Flag as human_review_only
- Do NOT auto-reassign

## Rollback

- DELETE FROM strategy_setup_matches WHERE run_label LIKE '%SP-2B-backfill%'
- This removes only backfill records, preserving any original route audit

## Insufficient Data

If ticker characteristics are too sparse to evaluate strategies (no price, no score):
- Skip backfill for that proposal
- Mark as 'insufficient_data_for_backfill'
