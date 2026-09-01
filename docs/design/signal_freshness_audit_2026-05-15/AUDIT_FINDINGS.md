# Signal Freshness & Persistence Audit — 2026-05-15

Status:      HISTORICAL
as_of:       2026-05-15T17:07:48-04:00
Measured at: efcc51365 / not measured

## Current Architecture

### Freshness filter location
**File:** `scripts/auto_proposal_generator.py`, line 208
```python
WHERE fired_at::date = CURRENT_DATE
```
This is the single freshness gate. Signals are only actionable on the calendar day they fire. At midnight, all signals expire regardless of strategy type.

### Freshness window: UNIFORM
All 20 strategies use the same `fired_at::date = CURRENT_DATE` filter. A momentum_scalp signal and a bond_income signal both expire at the same midnight boundary.

### Per-strategy variation: NO
No per-strategy TTL exists in the proposal generator. However, the strategy YAML configs DO have `proposal_expiry_hours` (e.g., 720h for position strategies, 8h for intraday), but this only affects how long a *proposal* lives — not how long the underlying *signal* stays eligible.

### Persistence infrastructure
- **Watchlist system:** 110 scripts reference watchlists, 169 API references, full UI page. Watchlist items are manually curated + agent-enriched.
- **Incubator system:** Separate from watchlists. Holds candidates with `status='ACTIVE'`, `days_active`, `promoted_to_proposal_at`. Persists across days. This is the closest thing to a persistent screener-derived watchlist.
- **Strategy signals table:** 264 KB, holds same-day signals only (wiped by the `CURRENT_DATE` filter).
- **trade_ai_scans table:** 792 KB, holds raw Finviz scan results. Not directly queried by the proposal generator.

## Observed Behavior (30 days)

### Per-strategy churn

| Strategy | Days Active | Total Ticker-Days | Unique Tickers | Avg Days/Ticker | Repeat % |
|----------|-------------|-------------------|----------------|-----------------|----------|
| momentum_scalp | 8 | 45 | 40 | 1.13 | 11.1% |
| gap_and_go | 8 | 30 | 26 | 1.15 | 13.3% |
| tax_loss_harvest | 5 | 20 | 16 | 1.25 | 20.0% |
| income_add | 5 | 20 | 16 | 1.25 | 20.0% |
| recovery_watch | 5 | 20 | 16 | 1.25 | 20.0% |
| sector_rotation | 5 | 20 | 16 | 1.25 | 20.0% |
| speculative_growth | 5 | 16 | 12 | 1.33 | 25.0% |
| swing_breakout | 5 | 15 | 14 | 1.07 | 6.7% |
| earnings_catalyst | 5 | 15 | 14 | 1.07 | 6.7% |
| dividend_growth_compounder | 2 | 2 | 1 | 2.00 | 50.0% |

**Key insight:** Repeat rates are low (6-25%) — most tickers are new each day. The incubator handles multi-day persistence already. Dedicated signal persistence would add complexity with limited benefit for most strategies.

### Most persistent tickers
**No tickers appeared on 3+ distinct days** within a single strategy in 30 days. The system naturally cycles through new names quickly.

### Cross-strategy overlap — CRITICAL FINDING
**MLGO and RCEL each appeared on 18 of 20 strategies.** This is a strategy classification bug — the classifier is mapping every scan to nearly every strategy. Symbols like TOPS, SNAL, LESL appear on 6-9 strategies each. This pollutes the signal pool and explains why so many garbage names reach the proposal stage.

### Scan-to-proposal lag

| Strategy | Proposals | Avg Hours | Max Hours |
|----------|-----------|-----------|-----------|
| momentum_scalp | 29 | 27.6h | 200.9h |
| gap_and_go | 9 | 24.6h | 78.0h |
| swing_breakout | 4 | 0.5h | 1.8h |
| recovery_watch | 1 | 56.2h | 56.2h |

**Key insight:** momentum_scalp signals average 27.6 hours from first scan to proposal — but the `CURRENT_DATE` filter should limit this to same-day. The 200h max means the signal persisted in the incubator and was promoted days later. The incubator IS providing multi-day persistence already.

## Recommended TTL by Strategy

| Strategy | Current TTL | Recommended TTL | Change |
|----------|------------|-----------------|--------|
| momentum_scalp | 1 day | 4 hours | Tighten |
| gap_and_go | 1 day | 4 hours | Tighten |
| swing_breakout | 1 day | 5 trading days | Extend |
| earnings_catalyst | 1 day | Until earnings + 2d | Event-tied |
| speculative_growth | 1 day | 10 trading days | Extend |
| dividend_growth_compounder | 1 day | 30 trading days | Extend |
| recovery_watch | 1 day | 15 trading days | Extend |
| bond_income | 1 day | 60 trading days | Extend |
| defense_thesis | 1 day | 20 trading days | Extend |
| All others | 1 day | Strategy-specific | Per YAML |

## Architectural Options

### Option A — Per-strategy TTL on signals
Add `signal_ttl_hours` to `screener_config` or strategy YAML. Change line 208 from `fired_at::date = CURRENT_DATE` to `fired_at > NOW() - INTERVAL '1 hour' * signal_ttl`.

**Feasibility:** HIGH. One column, one query change.

### Option B — Persistent watchlist per strategy
New table `strategy_watchlist`. Auto-populated from screeners, auto-expired by TTL.

**Feasibility:** MEDIUM. The watchlist infrastructure is massive (110 scripts, 169 API refs, 36 tables). But it's manually curated, not screener-derived.

### Option C — Hybrid (RECOMMENDED)
The **incubator already does this** for slow-decay strategies. Fast strategies (scalp, gap_and_go) use the existing same-day signals. Slow strategies (income, recovery, dividend) already flow through the incubator with `days_active` tracking and multi-day persistence.

**Assessment:** The current architecture is closer to "working" than it appears. The main fix needed is:
1. Fix the strategy classifier (MLGO on 18 strategies is a bug)
2. Optionally tighten momentum_scalp to 4h instead of midnight
3. Leave slow strategies on the incubator path (already persistent)

## Side Observations (bugs found during audit, NOT fixed)

1. **Strategy classifier bug:** MLGO, RCEL, SIBN mapped to 16-18 strategies each. The classifier is not discriminating.
2. **momentum_scalp 200h lag:** Some proposals are created 8+ days after the original scan, via the incubator path. This is by design but means "stale" signals can still become proposals.
3. **No persistent tickers at 3+ days in strategy_signals:** This is because the `CURRENT_DATE` filter prevents signals from persisting. The incubator handles persistence instead.

## What This Audit Did NOT Change
- No code modified
- No database writes
- No screener configs changed
- A-1 risk gates: untouched
- A-4 pipeline fix: untouched
- All 18 screeners: untouched
- momentum_scalp: untouched
