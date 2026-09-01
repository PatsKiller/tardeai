# Phase 186J: Extended-Hours Risk Gates

Status:      HISTORICAL
as_of:       2026-06-02T01:02:56-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-02

## Context

Extended hours (premarket 4:00-9:30 ET, after-hours 16:00-20:00 ET) have thinner liquidity, wider spreads, and higher volatility. Paper trading should use stricter gates.

## Entry Gates (Extended Hours)

| Gate | Regular Hours | Extended Hours |
|------|---------------|----------------|
| Max spread % | 0.5% | **1.0%** |
| Min volume (shares/5min) | 1,000 | **500** |
| Order type | Market or limit | **Limit only** |
| Bracket orders | Allowed | **NOT allowed** (Alpaca restriction) |
| Max position size | 5% of account | **2.5% of account** (half) |
| Max notional per trade | $5,000 | **$2,500** |
| Quote freshness | 60 seconds | **30 seconds** |
| Catalyst required | Preferred | **Required** (no low-conviction entries) |
| Hermes disagreement | Warning | **Block if DISAGREE + low evidence** |
| Price gap from proposal | 2% drift OK | **1% drift max** |
| Strategy restriction | All | **momentum_scalp, gap_and_go blocked** (intraday strategies need regular hours liquidity) |

## Exit Gates (Extended Hours)

| Gate | Rule |
|------|------|
| Stop hit | ALLOW — risk management must not be deferred |
| Target hit | ALLOW — lock profit when available |
| Trailing stop | DEFER to market open (unless loss > 2R) |
| Manual close | ALLOW |
| Market sell | BLOCKED — use limit at current bid |
| Time stop | DEFER to market hours |
| Phantom close | ALLOW (position already gone) |

## Spread Verification

Before submitting an extended-hours order:

```python
quote = get_latest_quote(symbol)
spread_pct = (quote.ask - quote.bid) / quote.mid * 100

if spread_pct > 1.0:
    REJECT "spread_too_wide_extended_hours"

if quote.age_seconds > 30:
    REJECT "stale_quote_extended_hours"
```

## Logging

Every extended-hours submission must log:
- `market_session: 'premarket' | 'afterhours' | 'regular'`
- `spread_at_submit_pct`
- `volume_at_submit`
- `quote_age_seconds`
- `extended_hours_gate_result: 'PASS' | 'FAIL_SPREAD' | 'FAIL_VOLUME' | 'FAIL_QUOTE_AGE'`

## Strategy-Specific Extended-Hours Rules

| Family | Extended Entry | Extended Exit |
|--------|---------------|---------------|
| momentum | BLOCKED | stops only |
| swing | ALLOWED (with spread gate) | ALLOWED |
| income | ALLOWED | ALLOWED |
| position | ALLOWED | ALLOWED |
| unknown | BLOCKED | stops only |

## Implementation Status

- Alpaca adapter: Already handles extended_hours flag and limit-only enforcement
- Risk gates: NOT YET IMPLEMENTED — design only
- Spread check: NOT YET IMPLEMENTED
- Volume check: NOT YET IMPLEMENTED
- Session logging: NOT YET IMPLEMENTED
