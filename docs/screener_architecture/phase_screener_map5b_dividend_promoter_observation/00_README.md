# MAP-5B — Dividend Income Promoter Observation

**Status:** COMPLETE
**Date:** 2026-05-21

## Observation Summary

Ran production promoter manually. 15 candidates evaluated, 0 promoted this run.

### Family Thresholds Confirmed Working

| Symbol | Strategy | Family | Spread | Threshold | Result |
|--------|----------|--------|--------|-----------|--------|
| AIAI | gap_and_go | GAP_EVENT | 19.3% | 3.0% | BLOCKED ✓ |
| AIAI | momentum_scalp | INTRADAY_MOMENTUM | 19.3% | 3.0% | BLOCKED ✓ |
| AIAI | earnings_post | EARNINGS_POST | 19.3% | 5.0% | BLOCKED ✓ |
| AIAI | technical_pattern | TECHNICAL_PATTERN | 19.3% | 5.0% | BLOCKED ✓ |
| NEE | dividend_growth | DIVIDEND_INCOME | - | 8.0% | BLOCKED (quote + R:R) |
| EZGO | recovery_watch | RECOVERY_WATCH | 20.9% | 5.0% | BLOCKED ✓ |
| CVM | recovery_watch | RECOVERY_WATCH | 17.1% | 5.0% | BLOCKED ✓ |

### DIVIDEND_INCOME Candidate (NEE)

NEE was evaluated as `dividend_growth_compounder` and blocked by:
1. `rr_below_minimum: 2.00 < 2.0` — R:R exactly at boundary
2. `quote_never_checked` — no execution-eligible quote

The MAP-5 score floor (15) was NOT the blocker — NEE would pass it. The blockers are legitimate pre-promotion gates that require quote data and minimum R:R.

### New Proposals/Trades (from earlier this session)

- **#106 KDK** (swing_trade) — PENDING
- **#107 ASPN** (swing_trade) — APPROVED_FOR_PAPER_TEST (approved via API/Telegram)
- **Trade #26 ASPN** — created by normal approval flow, status=pending, broker=None

These were created by the MAP-4B promoter run earlier, not MAP-5B.

### Income/Dividend Proposals: 0 New

No income/dividend proposals created because:
1. Only NEE passes the score floor (15) among income candidates
2. NEE blocked by quote + R:R gates (legitimate)
3. Other income candidates have scores below 15 in the incubator

### Why Income Proposals Will Take Time

The income pipeline needs:
1. **Dividend yield data in enrichment cache** — currently missing for all symbols
2. **Proactive quote refresh** on income candidates — `quote_never_checked` blocks promotion
3. **More incubator candidates with score ≥ 15** — most income candidates scored 10-20 in momentum-oriented scans

## Safety

| Check | Result |
|-------|--------|
| Trades created by MAP-5B | NO (trade #26 was from earlier approval) |
| Orders submitted | NO |
| Proposals approved by MAP-5B | NO |
| Strategy activation changed | NO |
| YAML/Finviz changed | NO |
| ALPACA_MODE=paper | Verified |
