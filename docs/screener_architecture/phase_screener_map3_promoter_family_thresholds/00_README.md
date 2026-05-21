# SCREENER-MAP-3 — Promoter Family Thresholds

**Status:** COMPLETE
**Date:** 2026-05-21

## Shadow Simulation Results (1,000 incubator candidates)

| Family | Total | Ready | Blocked | Issue |
|--------|-------|-------|---------|-------|
| DIVIDEND_INCOME | 155 | **155** | 0 | Ready — family thresholds pass them |
| RECOVERY_WATCH | 185 | 169 | 16 | Mostly ready |
| MEDIUM_SWING | 148 | 93 | 55 | Score/catalyst gates |
| SECTOR_ROTATION | 86 | 81 | 5 | Ready |
| CORE_GROWTH | 28 | 27 | 1 | Ready |
| TECHNICAL_PATTERN | 27 | **27** | 0 | Ready |
| GAP_EVENT | 41 | 38 | 3 | Ready |
| INTRADAY_MOMENTUM | 51 | 23 | 28 | Strict gates correct |
| EARNINGS_CATALYST | 241 | 0 | **241** | Needs earnings date evidence |
| EARNINGS_PRE | 18 | 0 | **18** | Needs earnings date evidence |
| EARNINGS_POST | 10 | 0 | **10** | Needs earnings date/catalyst |
| CORE_INDEX | 4 | 4 | 0 | Ready |
| FIXED_INCOME | 3 | 3 | 0 | Ready |
| THEMATIC | 2 | 2 | 0 | Ready |
| OPTIONS_INCOME | 1 | 0 | 1 | Provider missing |

**622 ready (62%) / 377 blocked (38%) / 1 provider missing**

## Key Finding

The **generic 3% spread gate** in the current promoter is the primary blocker for income/dividend strategies. With family-specific thresholds:
- DIVIDEND_INCOME: 155 candidates would pass (currently 0 proposals because spread gate blocks most income stocks)
- TECHNICAL_PATTERN: 27 candidates would pass (no special requirements beyond what they have)
- EARNINGS families: ALL blocked because they genuinely need earnings date data that doesn't exist yet

## Family Threshold Policy

`promoter_family_threshold_policy.py` defines thresholds for 16 strategy families:

| Family | Max Spread | Min RVOL | Min Score | Requires |
|--------|-----------|----------|-----------|----------|
| INTRADAY_MOMENTUM | 3% | 3.0 | 35 | Catalyst, fresh quote, market hours |
| GAP_EVENT | 3% | 2.0 | 30 | Catalyst, fresh quote, market hours |
| SHORT_SWING | 5% | 1.5 | 25 | Fresh quote |
| MEDIUM_SWING | 5% | 1.0 | 20 | Fresh quote |
| DIVIDEND_INCOME | **8%** | **0.0** | **10** | Dividend data (preferred) |
| FIXED_INCOME | **10%** | **0.0** | **5** | — |
| EARNINGS_CATALYST | 5% | 1.0 | 20 | **Earnings date**, catalyst |
| EARNINGS_PRE | 5% | 0.5 | 15 | **Earnings date** |
| EARNINGS_POST | 5% | 1.0 | 20 | **Earnings date**, catalyst |
| TECHNICAL_PATTERN | 5% | 0.5 | 15 | Technical pattern (preferred) |
| OPTIONS_INCOME | 5% | 0.0 | 10 | **Options chain** |
| SECTOR_ROTATION | 5% | 0.5 | 15 | — |
| CORE_GROWTH | 5% | 0.0 | 15 | — |
| CORE_INDEX | 2% | 0.0 | 5 | — |
| THEMATIC | 5% | 0.5 | 15 | — |
| TAX_STRATEGY | 8% | 0.0 | 5 | — |

## MAP-4 Implementation Plan

### Ready for production (operator approval needed):
1. **DIVIDEND_INCOME** — 155 candidates ready, just need spread gate relaxation from 3% to 8%
2. **TECHNICAL_PATTERN** — 27 candidates ready, current gates sufficient
3. **CORE_GROWTH** — 27 ready
4. **SECTOR_ROTATION** — 81 ready
5. **RECOVERY_WATCH** — 169 ready (already producing, just more with relaxed thresholds)

### Blocked by provider (future work):
1. **EARNINGS families** — need earnings calendar API (Alpha Vantage, Yahoo, Earnings Whispers)
2. **OPTIONS_INCOME** — need options chain provider (Alpaca options, CBOE)

### Already working:
- INTRADAY_MOMENTUM, GAP_EVENT — current gates are correct for these

## Safety
- No proposals created
- No trades created
- No orders submitted
- No strategy activation changed
- No YAML thresholds changed
- No Finviz criteria changed
- No production promoter behavior changed
- Shadow simulation only
