# v3.6 Journal / Learning / Backtesting Implementation Report

**Date:** 2026-05-27

## Files Changed

| File | Change |
|------|--------|
| `scripts/api_v2.py` | Added `/api/v2/lifecycle/journal-learning-summary` + `/api/v2/lifecycle/trade-case-study` |
| `scripts/lib/journal_learning.py` | NEW — read-only helper with ghost detection |
| `apps/command-center-v2/src/components/JournalLearningWorkspace.tsx` | NEW |
| `apps/command-center-v2/src/pages/ATMControlRoom.tsx` | Added JournalLearningWorkspace compact |

## API Results

| Field | Value |
|-------|-------|
| open_trade_count | 4 |
| clean_closed_count | 12 |
| ghost_count | 18 |
| traced_closed_trade_count | 29 |
| execution_quality_count | 10 |
| stop_audit_event_count | varies |
| missed_proposal_count | varies |
| duplicate_contamination_status | contaminated (ghost rows exist but excluded from clean metrics) |

## Strategy Summary (top 5)

| Strategy | Closed | Win Rate |
|----------|--------|----------|
| swing_breakout | 3 | 100% |
| swing_trade | 2 | 50% |
| earnings_catalyst | 2 | 50% |
| momentum_scalp | 2 | 0% |
| dividend_growth_compounder | 2 | 50% |

## BLMN Validation

- #37 excluded from active/open: YES (exit_reason=duplicate_submit_race)
- #38 preserved as real open: YES (case study returns id=38, no exit_reason)

## Build: Clean (327ms)

## Note on broker/account references

APIs use the `account` field from paper_trades (e.g., ALPACA_PAPER, TOS_PAPER) — not hardcoded.
Safety blocks reference `ALPACA_MODE` env var which is the system's own configuration.

## Safety

- No orders placed
- No broker writes
- No paper_trades changes
- No proposal changes
- No journal mutations
- No backtest mutations
- ALPACA_MODE=paper, LLM_DISABLE=true

## Rollback

```bash
git revert HEAD
```
