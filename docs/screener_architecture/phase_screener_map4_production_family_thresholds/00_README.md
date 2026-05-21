# SCREENER-MAP-4 — Production Family Thresholds

**Status:** COMPLETE
**Date:** 2026-05-21

## What Changed in Production

Two targeted changes to `incubator_proposal_promoter.py`:

### 1. Family-specific spread gate (was hard 3.0% for all)

```python
# BEFORE:
if _spread > 3.0:  # blocks all income/dividend stocks

# AFTER:
_family_th = get_family_thresholds(strategy_id)
_max_spread = _family_th.get("max_spread_pct", 3.0)
if _spread > _max_spread:  # family-appropriate threshold
```

**Impact by family:**
| Family | Old Spread Gate | New Spread Gate | Change |
|--------|----------------|-----------------|--------|
| INTRADAY_MOMENTUM | 3% | 3% | No change |
| GAP_EVENT | 3% | 3% | No change |
| SHORT_SWING | 3% | 5% | Relaxed |
| MEDIUM_SWING | 3% | 5% | Relaxed |
| DIVIDEND_INCOME | 3% | **8%** | Operator-approved |
| FIXED_INCOME | 3% | **10%** | Relaxed |
| EARNINGS families | 3% | 5% | Relaxed |
| TECHNICAL_PATTERN | 3% | 5% | Relaxed |
| OPTIONS_INCOME | 3% | 5% | Relaxed |
| SECTOR_ROTATION | 3% | 5% | Relaxed |
| CORE_GROWTH | 3% | 5% | Relaxed |
| CORE_INDEX | 3% | 2% | Tightened (ETFs) |

### 2. Block generic `strategy_id='screener'`

Prevents proposals from being created with the generic "screener" strategy. Candidates must be classified into a real strategy first.

## What Did NOT Change

- Execution approval gates — unchanged
- Risk gates — unchanged
- Quote readiness — unchanged
- Route audit — unchanged
- YAML thresholds — unchanged
- Finviz screener criteria — unchanged
- Strategy activation — unchanged
- Approval process — still operator-reviewed

## Promoter Readiness ≠ Execution Approval

The spread gate relaxation only affects **promoter readiness** (whether a candidate can become a proposal). It does NOT affect:
- Whether the proposal can be approved
- Whether a quote is execution-eligible
- Whether risk gates pass
- Whether the operator approves

## Safety

- ALPACA_MODE=paper
- No trades created
- No orders submitted
- No strategy activation changed
- No YAML thresholds changed
- No Finviz criteria changed
- Rollback: `scripts/rollback_screener_map4_promoter_thresholds.sh`
