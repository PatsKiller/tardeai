# SP-2C Scope — Wire Route Audit into Proposal Creation

## Purpose

Wire `multi_setup_router.route_symbol()` + `store_setup_matches()` into all 4 proposal
creation paths so future proposals get route audit evidence automatically.

## What Changed

- Created `scripts/proposal_route_audit_integration.py` — shared helper
- Wired into `auto_proposal_generator.py` after INSERT RETURNING
- Wired into `incubator_proposal_promoter.py` after INSERT RETURNING
- Wired into `paper_trade_logger.py` both scan and manual paths after INSERT RETURNING

## Behavior

- Route audit runs after proposal INSERT, before commit
- All 23 YAML strategies evaluated for each proposal
- Setup matches stored with source label (e.g. `SP-2C-auto_proposal_generator`)
- Original proposal strategy_id is NEVER changed
- Invalid strategy_id (e.g. 'screener') flagged but not auto-corrected
- If router fails, proposal still created but logged as warning
- Route audit is idempotent (checks for existing records)

## What Did NOT Change

- Strategy activation — NO
- YAML thresholds — NO
- Historical proposals — NOT reassigned
- Approval gates — NOT weakened (only blockers added by PP-UX-2/SP-2B)
- Execution logic — NO
- Trade creation — NO
- Order submission — NO
