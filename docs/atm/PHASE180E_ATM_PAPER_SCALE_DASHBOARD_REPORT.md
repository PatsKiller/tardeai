# Phase 180E: ATM Paper Scale Dashboard Report

Status:      HISTORICAL
as_of:       2026-06-01T23:26:38-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Mode**: PAPER ONLY — Level 7 PROHIBITED

## Dashboard Implementation

The paper trading readiness dashboard is integrated into the Paper Trading Status page (`/paper-status`) as a top-of-page widget showing:

### Statistical Readiness Widget (Phase 179E)

Located at top of `/paper-status` page:
- Readiness level badge (P0-P5)
- LIVE TRADING PROHIBITED banner
- 6 KPI tiles: Usable Trades, Distance to 2,000, Distance to 4,000, Win Rate, Profit Factor, Net PnL
- Progress bars to 2,000 and 4,000 targets

### API Endpoint

`GET /api/v2/paper-trade-readiness`

Returns:
- `level`: P0_NOT_ENOUGH_DATA through P5_LIVE_READINESS_CANDIDATE
- `closed_usable`: Number of usable closed trades
- `distance_to_2000`, `distance_to_4000`: Trades remaining
- `pct_to_2000`, `pct_to_4000`: Completion percentage
- `win_rate`, `profit_factor`, `expectancy`, `net_pnl`: Performance
- `journal_completeness`: Per-field completion percentages
- `linkage`: Thesis, outcome, Hermes, backtest linkage percentages
- `top_strategies`: Strategy breakdown with sample sizes
- `live_trading_prohibited: true`
- `level_7_prohibited: true`

### Existing ATM Metrics (Already on Page)

The Paper Trading Status page already displays:
- Alpaca API status (connected/disconnected)
- Account equity, buying power, cash
- Open positions and orders
- Adapter health (enabled, trading blocked)
- Halt flags
- Risk status
- Today's activity summary
- Open trades intelligence panel

### ATM Validation Dashboard Fields (Phase 180E)

| Field | Source | Location |
|-------|--------|----------|
| Paper account value | Alpaca API | Alpaca API card |
| Current buying power | Alpaca API | Alpaca API card |
| Today paper trades | paper_trades count | Today Summary |
| Open paper positions | Alpaca API | Alpaca API card |
| Average trade size | paper_trade_statistics | Readiness widget |
| Average notional | paper_trade_statistics | Readiness widget |
| Trades toward 2,000 | paper_trade_statistics | Readiness widget |
| Trades toward 4,000 | paper_trade_statistics | Readiness widget |
| Journal completeness | paper_trade_statistics | Readiness widget |
| Exit completeness | paper_trade_statistics | Readiness widget |
| Stop completeness | paper_trade_statistics | Readiness widget |
| Strategy distribution | paper_trade_statistics | API response |
| Kill switch status | ATM state | Halt Flags card |
| Readiness level | paper_trade_statistics | Readiness widget |

### CLI Monitoring

```bash
# Run statistics report
python scripts/paper_trade_statistics.py

# Check ATM state
python scripts/atm_auto_approver.py --status

# Check live trading gate
python scripts/live_trading_gate.py --status --json
```

## Current Dashboard State

All metrics currently visible on the `/paper-status` page with the readiness widget added in Phase 179E. No additional dashboard changes needed — the existing page combines ATM operational status with statistical readiness tracking.
