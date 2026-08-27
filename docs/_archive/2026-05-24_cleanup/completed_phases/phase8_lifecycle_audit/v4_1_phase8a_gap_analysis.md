# Phase 8A Gap Analysis

## P0 — Required Before Outcome Scoring

| Gap | Evidence | Fix |
|-----|----------|-----|
| Feedback observations lack paper_trade_id | 317 observations, no trade FK | Add paper_trade_id column to llm_feedback_observations |
| Approval audit only 1 row | Phase 6C built after most trades | No fix needed — new trades will have audit |

## P1 — Needed for Strategy Scoring

| Gap | Evidence | Fix |
|-----|----------|-----|
| 5 trades missing proposal_id | Pre-pipeline trades | Backfill from symbol/date matching if possible |
| No MFE/MAE data | Fields don't exist on paper_trades | Add mfe_pct, mae_pct columns in Phase 8B |
| No outcome_label field | Trades have pnl/exit_reason but no WIN/LOSS/BREAKEVEN label | Add outcome_label column or compute from pnl |

## P2 — Nice-to-Have

| Gap | Evidence | Fix |
|-----|----------|-----|
| No simulator-to-proposal link | Phase 7 is stateless | Optional audit table if needed |
| Stop/target version history | Changes not tracked | Add stop_change_log if needed |

## P3 — Future

| Gap | Evidence | Fix |
|-----|----------|-----|
| Cross-strategy outcome comparison | Requires 20+ closed trades per strategy | Wait for more data |

## Summary

9 closed trades exist with complete data (exit_reason, pnl, r_multiple, closed_at). The lifecycle joins are strong enough for basic outcome scoring. Main addition needed: outcome_label column (trivially computed from pnl).
