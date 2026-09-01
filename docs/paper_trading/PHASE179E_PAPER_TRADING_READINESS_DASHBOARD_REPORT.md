# Phase 179E: Paper Trading Readiness Dashboard Report

Status:      HISTORICAL
as_of:       2026-06-01T23:21:01-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Mode**: PAPER ONLY

## Dashboard Implementation

### API Endpoint

- **Route**: `GET /api/v2/paper-trade-readiness`
- **Source**: Reads `data/paper_trading/paper_trade_statistics_latest.json`
- **Fallback**: Runs `paper_trade_statistics.compute_statistics()` live if file missing
- **Refresh**: 120s poll interval

### Dashboard Widget Location

- **Page**: Paper Trading Status (`/paper-status`)
- **Position**: Top of page, above Open Trades
- **Component**: Statistical Readiness panel with:
  - Readiness level badge (P0/P1/P2/P3/P4/P5 color-coded)
  - LIVE TRADING PROHIBITED banner
  - 6 KPI tiles: Usable Trades, Distance to 2,000, Distance to 4,000, Win Rate, Profit Factor, Net PnL
  - Progress bars: To 2,000 (amber) and To 4,000 (red)

### Data Fields Displayed

| Field | Source | Current Value |
|-------|--------|---------------|
| Readiness Level | readiness.level | P0_NOT_ENOUGH_DATA |
| Usable Trades | readiness.closed_usable | 24 |
| Distance to 2,000 | readiness.distance_to_2000 | 1,976 |
| Distance to 4,000 | readiness.distance_to_4000 | 3,976 |
| % to 2,000 | readiness.pct_to_2000 | 1.2% |
| % to 4,000 | readiness.pct_to_4000 | 0.6% |
| Win Rate | performance.win_rate | 45.8% |
| Profit Factor | performance.profit_factor | 6.35 |
| Net PnL | performance.net_pnl | $1,853 |
| Live Trading | live_trading_prohibited | TRUE |
| Level 7 | level_7_prohibited | TRUE |

### Statistics Script

- **Script**: `scripts/paper_trade_statistics.py`
- **Output**: `data/paper_trading/paper_trade_statistics_latest.json`
- **CLI**: `python scripts/paper_trade_statistics.py` (human-readable)
- **CLI JSON**: `python scripts/paper_trade_statistics.py --json`
