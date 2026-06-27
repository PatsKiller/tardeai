# TradeInView Implementation Plan

**Module:** TradeInView — trading journal, performance analytics, self-improvement  
**Route:** `/v3/journal` (alias `/v3/trade-in-view`)  
**Status:** P0–P4 shipped 2026-06-27; P5–P6 partial

## Architecture

```
Schwab API / CSV ──► trade_transactions ──► schwab_round_trips ──► trade_closed
Paper ATM ─────────► paper_trades ──► automated-trade-journal API
                              │
                              ▼
                    JournalHub (TradeInView UI)
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
 journal_trade_reviews   trade_execution_quality   trade_profit_capture_analysis
        │                     │                     │
        └──────────► journal_trade_in_view.py ◄────┘
                              │
                    /api/v2/journal/* endpoints
```

## Tabs

| Tab | Purpose |
|-----|---------|
| Trades | KPIs, equity, calendar, trade log (cards/table), execution coach |
| Analytics | Zella score, edge analytics, ask journal |
| Exit Intel | MAE/MFE, capture, EOD vs intraday, exit timing |
| Behavioral | Tilt, revenge, mistake $, streak impact |
| Lessons | Closed-trade lessons feed |
| Protection | Protection outcomes |
| Backtesting | Hypotheses + backtest panel |
| Real Accounts | Schwab round-trips |
| Import | CSV import, manual entry, options summary |

## APIs (new)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v2/journal/exit-intelligence` | GET | Exit quality analytics |
| `/api/v2/journal/zella-score` | GET | Composite 0–100 score |
| `/api/v2/journal/behavioral` | GET | Psychology / tilt reports |
| `/api/v2/journal/sector-breakdown` | GET | P&L by sector |
| `/api/v2/journal/options-summary` | GET | Options trades in journal |
| `/api/v2/journal/export` | GET | CSV export |
| `/api/v2/journal/saved-filters` | GET/POST | Saved filter groups |
| `/api/v2/journal/tag-groups` | GET | Editable tag definitions |
| `/api/v2/journal/manual-entry` | POST | Manual trade row |
| `/api/v2/journal/import-csv` | POST | Schwab history CSV |

## DB migration

`migrations/2026_06_27_trade_in_view.sql` — `journal_saved_filters`, `journal_manual_entries`, `journal_tag_groups`

## Ops

```bash
# Apply migration
psql -f migrations/2026_06_27_trade_in_view.sql

# Backfill MFE + profit capture
.venv/bin/python scripts/backfill_trade_in_view_mfe.py

# Smoke analytics
.venv/bin/python scripts/journal_trade_in_view.py --exit --zella --behavioral
```

## Priority backlog (next sprints)

1. **P5 Options** — multi-leg ingest, greeks attribution in journal
2. **P6 Polish** — attachments, session recaps, Morning Brief tilt hook
3. **Annotation campaign** — 80% review coverage
4. **v2 deprecation** — redirect `/v2/journal*` → v3 TradeInView