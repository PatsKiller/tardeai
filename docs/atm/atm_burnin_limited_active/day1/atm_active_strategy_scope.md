# ATM Limited Active — Strategy Scope

**Status:** Prepared for Monday 2026-05-26

## Approved Strategy Candidates

Based on today's ATM activity (4 successful approvals):

| Strategy | Evidence | Approved? |
|----------|----------|-----------|
| `dividend_growth_compounder` | 4 approved today (NWG, NVDA, BCS, CMCSA) | YES |
| `reit_income` | 1 approved today (AGNC) | YES |
| `core_growth_compounder` | 1 approved today (ARM) | YES |

## Excluded (for burn-in)

All other strategies excluded until burn-in proves the above 3 are clean:
- `momentum_scalp` — same-day skip (ATM cadence too slow)
- `gap_and_go` — same-day skip
- `swing_trade` — B-1 bucket2 excluded until 2026-05-25
- `swing_breakout` — B-1 bucket2 excluded
- All others — insufficient evidence

## Validation Requirements Per Strategy

Each approved strategy must have at entry time:
- Valid route audit
- Valid strategy_id (exists in YAML)
- Fresh Alpaca quote (< 60s)
- R:R ≥ 2.0
- Broker-native stop order confirmed
- stop_order_id tracked
- Enrichment status = COMPLETE
