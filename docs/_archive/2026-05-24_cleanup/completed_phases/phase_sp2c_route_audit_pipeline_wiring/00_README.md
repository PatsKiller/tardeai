# SP-2C — Wire Route Audit into Proposal Creation Pipeline

**Status:** COMPLETE

## Purpose

Fixes the root cause found in SP-2/SP-2B: proposal creation paths bypassed
`multi_setup_router`, so 89% of proposals had no route audit evidence.

## What Was Done

Created `scripts/proposal_route_audit_integration.py` — shared helper that:
- Loads all 23 YAML strategy configs
- Calls `multi_setup_router.route_symbol()` to evaluate all strategies
- Stores setup matches via `store_setup_matches()`
- Preserves original proposal strategy_id (NEVER changes it)
- Flags invalid strategy_id (e.g. 'screener') as a blocker
- Handles router failures gracefully (warning, not crash)

Wired into all 4 proposal creation paths:
1. `auto_proposal_generator.py` — after INSERT RETURNING
2. `incubator_proposal_promoter.py` — after INSERT RETURNING
3. `paper_trade_logger.py` (scan path) — after INSERT RETURNING
4. `paper_trade_logger.py` (manual path) — after INSERT RETURNING

## Result

Every future proposal will have route audit evidence showing:
- Which of 23 strategies were evaluated
- Match scores and pass/fail for each
- Top match vs assigned strategy (mismatch detection)
- Invalid strategy_id blocker

## Safety

- Original strategy_id preserved
- No strategy activation changes
- No YAML changes
- No trade creation
- No order submission
- Tests: 17/17, SP-2B regression 17/17
