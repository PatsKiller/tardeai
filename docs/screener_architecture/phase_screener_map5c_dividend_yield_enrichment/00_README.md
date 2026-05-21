# MAP-5C — Dividend Yield Enrichment

**Status:** COMPLETE
**Date:** 2026-05-21

## What Changed

### 1. Enrichment cache updated with Finviz v=161 fundamentals
Ran `finviz_enrichment.py` on 150 income/dividend incubator symbols. Finviz v=161 view provides `div_yield_pct`, `roe_pct`, `roa_pct`, `gross_margin_pct`, `profit_margin_pct`, `debt_equity`.

**Result:** 23 of 150 income candidates now have `div_yield_pct` data. The remaining 127 have `None` because they're small-cap stocks that don't pay dividends despite being classified as dividend strategies.

### 2. Scoring policy updated
`dividend_income_scoring_policy.py` now reads `div_yield_pct` (the actual Finviz field name) and uses ROE + debt/equity in safety scoring.

**Before (NEE, no yield in cache):** score=47
**After (WEN, with 8% yield):** score=58

### 3. Promoter observation
NEE still blocked by `quote_never_checked` — correct behavior. The pre-promotion gate requires an execution-eligible quote. Enrichment data (yield, PE, ROE) informs the scoring but doesn't bypass the quote gate.

## Key Finding: Classification ≠ Dividend Payer

Most "dividend" incubator candidates (127/150) don't actually pay dividends. They were classified as `dividend_growth_compounder` by the multi-strategy classifier based on other characteristics (sector, PE, stability). Only 23 have real dividend yield data from Finviz.

This means:
- The DIVIDEND_INCOME scoring works correctly for real dividend payers (WEN scores 58)
- Non-dividend-paying stocks classified as "dividend" score lower (NEE scores 33) but still pass the floor 15
- The `quote_never_checked` gate is the actual remaining blocker, not the scoring

## Next Steps
1. Run proactive quote refresh on the 23 enriched dividend payers
2. The hourly screener will gradually refresh quotes via normal cycle
3. Once quotes are available, NEE and similar candidates can be promoted

## Safety
- No trades/orders created
- No YAML/Finviz changes
- No strategy activation changes
- ALPACA_MODE=paper
