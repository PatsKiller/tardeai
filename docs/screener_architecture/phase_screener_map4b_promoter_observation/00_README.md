# SCREENER-MAP-4B — Post-Wire Promoter Observation

**Status:** COMPLETE
**Date:** 2026-05-21

## Observation Summary

Promoter ran manually after MAP-4 wiring. **Family thresholds are working correctly.**

### New Proposals Created: 2

| # | Symbol | Strategy | Entry | Stop | Target | Status |
|---|--------|----------|-------|------|--------|--------|
| 106 | KDK | swing_trade | $6.03 | $5.73 | $6.63 | PENDING |
| 107 | ASPN | swing_trade | $5.42 | $5.15 | $5.96 | PENDING |

Both are swing_trade candidates that passed the new 5% family spread gate (were previously blocked by the hard 3% gate).

### Family Threshold Behavior Confirmed

| Symbol | Spread | Family | Threshold | Result |
|--------|--------|--------|-----------|--------|
| GOVX | 35.5% | RECOVERY_WATCH | 5.0% | BLOCKED ✓ |
| GOVX | 35.5% | SECTOR_ROTATION | 5.0% | BLOCKED ✓ |
| OSS | 33.7% | MEDIUM_SWING | 5.0% | BLOCKED ✓ |
| INFU | 14.9% | MEDIUM_SWING | 5.0% | BLOCKED ✓ |
| ATRA | 34.0% | MEDIUM_SWING | 5.0% | BLOCKED ✓ |
| KDK | <5% | MEDIUM_SWING | 5.0% | PROMOTED ✓ |
| ASPN | <5% | MEDIUM_SWING | 5.0% | PROMOTED ✓ |

The log correctly shows the family name and threshold in skip messages (e.g., "spread_35.5pct > 5.0% for RECOVERY_WATCH").

### No DIVIDEND_INCOME Proposals Yet

No income/dividend candidates had fresh enough scan data to be picked up by this promoter run. The 155 DIVIDEND_INCOME incubator candidates exist but need to appear in a fresh `trade_ai_scans` run with GO/WAIT decision before the promoter can evaluate them. The next screener run should produce candidates.

### Known Issue: `name 'rr' is not defined`

The pre-promotion check has a bug where `rr` variable is referenced before assignment for newly promoted proposals. This doesn't prevent promotion but blocks the Telegram alert for new proposals. Non-critical — the proposals were created correctly.

### Safety Verification

| Check | Result |
|-------|--------|
| Proposals created | 2 (PENDING, operator review required) |
| Trades created | **0** |
| Orders submitted | **0** |
| Strategy activation changed | **NO** |
| YAML changed | **NO** |
| Finviz criteria changed | **NO** |
| Execution approval given | **NO** — proposals are PENDING |
| strategy_id='screener' | **BLOCKED** (not seen in output) |
