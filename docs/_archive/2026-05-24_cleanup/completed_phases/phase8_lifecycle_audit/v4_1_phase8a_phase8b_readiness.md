# Phase 8B Readiness Assessment

## Can Phase 8B Proceed?

**YES — with limited scope.** 9 closed trades with complete lifecycle data is enough for basic outcome labeling and initial scoring infrastructure. Not enough for statistically significant strategy comparison.

## Data Available

| Metric | Count | Sufficient? |
|--------|-------|-------------|
| Closed trades | 9 | Minimal — enough for schema + logic |
| With exit_reason | 9/9 | YES |
| With pnl | 9/9 | YES |
| With r_multiple | 9/9 | YES |
| With proposal_id | 7/9 | Mostly |
| Strategies represented | 6 | Partial |
| Journal reviews | 19 | YES |

## Should A-5 Run First?

**YES.** A-5 observation window ends 2026-05-22. By then, the pipeline (19+ proposals/day) should have generated more closed trades. Recommend:
1. Complete Phase 8A discovery now (done)
2. Wait for A-5 observation end
3. Start Phase 8B with schema additions after A-5

## Recommended Phase 8B Scope (Minimum Safe)

1. Add `outcome_label` column to paper_trades (WIN/LOSS/BREAKEVEN)
2. Backfill outcome_label from existing pnl data
3. Add strategy scoring report (win_rate, avg_r, profit_factor by strategy)
4. Connect feedback observations to paper_trade_id where possible
5. Do NOT auto-apply strategy changes — human-review only

## What to Defer

- MFE/MAE computation (needs intraday price data)
- Cross-strategy comparison (needs 20+ trades per strategy)
- Automated strategy retirement (needs governance approval)
- Stop architecture tuning (needs separate analysis)
