# MAP-5D — Dividend Quote Refresh

**Status:** COMPLETE
**Date:** 2026-05-21

## What Changed

### 1. Quote refresh selector updated for family-specific thresholds
`select_quote_refresh_targets.py` previously hardcoded `latest_score >= 38`, which excluded all DIVIDEND_INCOME candidates (floor=15). Updated to import `promoter_family_threshold_policy` and use per-family `min_score` thresholds.

**Before:** 0 dividend/income candidates selected for quote refresh
**After:** 142 dividend/income candidates eligible for refresh

### 2. Proactive quote refresh executed on 142 symbols
Ran `get_best_quote()` → `store_quote()` pipeline via Alpaca for all ACTIVE dividend/income incubator candidates with score >= 15 that had no quote within 24 hours.

**Result:** 142/142 refreshed, 0 failed. All quotes execution-eligible (Alpaca provider).

### 3. Promoter observation (dry-run)
Ran `incubator_proposal_promoter.py --dry-run` after quote refresh:

**32 candidates WOULD PROMOTE** including:
- NEE (dividend_growth_compounder, score=30, previously blocked by `quote_never_checked`)
- AGNC (reit_income, score=26)
- CMCSA (dividend_growth_compounder, score=25)
- NVDA (dividend_growth_compounder, score=22)
- INTU (dividend_growth_compounder, score=20)
- KVUE (dividend_growth_compounder, score=17)
- ABR (reit_income, score=17)
- REYN (dividend_growth_compounder, score=15)
- ING (dividend_growth_compounder, score=15)

**Appropriately blocked:**
- KEYS (spread 12.5% > 8.0% for DIVIDEND_INCOME)
- MLGO (spread 31.6%)
- PGNY (RSI 78 elevated)
- CYRX (RSI 77 elevated)

### 4. Zero proposals created
Dry-run only. The A-5 observation window continues through 2026-05-22.

## Key Findings

1. **Quote gate was the last blocker for dividend candidates** — enrichment (MAP-5C) + scoring (MAP-5) + family thresholds (MAP-4) were all working, but symbols couldn't promote without any quote data
2. **The quote selector excluded dividend candidates by design** — the hardcoded score >= 38 threshold was calibrated for momentum strategies, not income/dividend families
3. **Spread gates still filter appropriately** — wide-spread micro-caps correctly blocked even after quote refresh
4. **RSI gates work on dividend stocks** — PGNY (RSI 78) and CYRX (RSI 77) correctly blocked from promotion despite having quotes

## Files Changed
- `scripts/select_quote_refresh_targets.py` — Use family-specific min_score thresholds instead of hardcoded 38

## Safety
- No trades/orders created
- No proposals created (dry-run only)
- No .env changes
- No strategy activation changes
- ALPACA_MODE=paper verified
- LLM_DISABLE_LIVE_EXECUTION=true verified
