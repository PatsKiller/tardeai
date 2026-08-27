# Session 18D: End-to-End Paper Proposal Smoke Test + Run Label Cleanup

## Summary
Verified the full paper proposal lifecycle end-to-end and fixed critical bugs.

## Run Label Lineage
- Added `source_run_label` and `auto_execution_label` columns to auto_proposal_runs, auto_proposal_decisions, and paper_trade_proposals
- Backfilled existing proposals: SMX → source_run_label=0900, MNKD → source_run_label=1000
- Auto generator now passes execution_label (manual/orchestrator/cron)

## Critical Bug Fix: POST Route Fallthrough
- **Root cause**: `return None` at line 9054 in api_v2.py handle() function terminated ALL POST routes that didn't match inside the initial POST block
- **Impact**: POST endpoints defined after the block (paper-proposals/approve, paper-proposals/reject, paper-proposals/run-research, etc.) were unreachable — always returned "Unknown endpoint"
- **Fix**: Removed the premature `return None`, allowing POST requests to fall through to paper-proposals routing

## End-to-End Smoke Test
1. **Signal** → strategy_signal #29 (SMX, momentum_scalp, A grade, score 42)
2. **Auto proposal** → paper_trade_proposal #3 (PENDING, auto_created, risk gate APPROVED)
3. **Approval** → POST /api/v2/paper-proposals/approve with proposal_id=3, confirmed=true
4. **Paper trade** → paper_trade #1 (open, TOS_PAPER, entry $1.29, stop $1.23, 1550 shares)
5. **Real journal** → clean (76 real trades, 0 paper contamination)
6. **Holdings** → $1,191,240 untouched

## Files Changed
- scripts/api_v2.py (POST route fallthrough fix, auto-proposal diagnostics)
- scripts/auto_proposal_generator.py (execution_label lineage)
- scripts/trade_ai_orchestrator.py (execution_label=orchestrator)
- sql/migrations/20260506_2200_session18d_run_label_lineage.sql

## Validation
- All syntax checks pass
- Frontend build: 175ms clean
- No duplicate proposals
- Real journal clean
- Holdings untouched
- Ready for Session 19
