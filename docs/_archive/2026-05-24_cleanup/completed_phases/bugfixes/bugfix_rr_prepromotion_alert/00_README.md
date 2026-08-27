# BUGFIX-RR-1 — Fix undefined `rr` in pre-promotion check

**Status:** FIXED
**Date:** 2026-05-21

## Root Cause

`incubator_proposal_promoter.py` line 659 referenced `rr` (risk/reward ratio) which was never computed. The variable was used in:
1. `pre_promotion_readiness_policy.evaluate_pre_promotion_readiness()` — line 659
2. Proposal creation INSERT — line 743

`entry`, `stop`, `target`, `shares` were computed at line 600 by `compute_levels()`, but R:R was never derived from them.

## Impact

- **Telegram alert**: BLOCKED — `NameError: name 'rr' is not defined` caught by except, alert skipped
- **Pre-promotion check**: FAILED — same error caught, check skipped (proposal still created)
- **Proposal creation**: `proposed_rr` set to `rr` which threw NameError — caught by outer try/except
- **Proposals remained PENDING**: Yes (KDK #106, ASPN #107)
- **Trades created**: NO
- **Orders submitted**: NO
- **Execution approval given**: NO

## Fix

Added R:R computation after `compute_levels()`:

```python
rr = round((target - entry) / (entry - stop), 2) if entry > stop and target > entry else 0
```

This is the standard R:R calculation: reward (target - entry) / risk (entry - stop).

## Safety

- No approval gates bypassed
- No R:R check bypassed — rr=0 would fail any R:R gate naturally
- No trades/orders created
- No strategy activation changed
- ALPACA_MODE=paper preserved
