# Strategy Classifier Strict Dry-Run Report

**Date:** 2026-05-28
**Model:** gemma3:4b (GPU, 41 layers)
**Sample size:** 20 trades

## Results Summary

| Metric | Count |
|--------|-------|
| Total sampled | 20 |
| Classified (exact strategy) | 0 |
| needs_review | 20 |
| unknown | 0 |
| errors | 0 |
| dividend_growth_compounder | 0 |
| Post-validation downgrades | 0 (model correctly self-classified) |

## Iteration History

| Run | dividend_growth | swing_trade | needs_review | errors | Issue |
|-----|-----------------|-------------|--------------|--------|-------|
| v0 (original) | 3/3 | 0 | 0 | 0 | Prompt biased to dividend |
| v1 (strict prompt) | 0 | 0 | 3 | 16 | JSON parse failures |
| v2 (parser fix) | 0 | 20 | 0 | 0 | Model over-defaulted to swing_trade |
| v3 (final) | 0 | 0 | 20 | 0 | Correct: insufficient evidence |

## ADBE Result After Fix

```json
{
  "strategy_id": "needs_review",
  "confidence": 0.4,
  "reasoning": "Only price and hold data available, insufficient to determine specific strategy",
  "evidence_used": ["hold_days=453", "pnl=-1074.80"],
  "missing_evidence": ["no proposal", "no strategy tag", "no catalyst data"],
  "requires_review": true
}
```

Correct. ADBE is no longer falsely classified as dividend_growth_compounder.

## Post-Validation Rules Active

1. **Dividend evidence gate**: dividend_growth_compounder requires dividend keywords in evidence_used
2. **Unsupported claim gate**: reasoning claiming "dividend stock" without evidence triggers downgrade
3. **Confidence cap**: >0.8 confidence with <2 evidence items capped at 0.6
4. **Hold period gate**: swing_trade with 30+ day hold downgraded to needs_review
5. **Confidence bounds**: needs_review capped at 0.5, unknown capped at 0.4

## Why 20/20 needs_review Is Correct

These are Schwab historical trades imported from trade_transactions. They contain ONLY:
- Price, dates, PnL, account info

They do NOT contain:
- Strategy tags, proposals, thesis, catalysts, technical indicators, market cap, RVOL, sector data

Without this metadata, the classifier honestly cannot distinguish between strategies. Classifying them as `needs_review` is the correct behavior — it prevents polluting the strategy_backtest_trades table with false labels.

## Is Full Apply Safe?

**NO.** Applying now would write `needs_review` to all unclassified trades, which is not useful. Full apply should wait until:

1. **Trade data enrichment**: Add proposal/thesis data, strategy tags, or sector info to the trades view
2. **Symbol-level lookup**: Build a deterministic lookup for well-known symbols (SPY=core_index, RTX=defense_thesis, etc.) that doesn't require LLM
3. **Historical strategy mapping**: Manual classification of representative trades to train the model

## Recommendation

1. Do NOT run --apply on current data
2. Build a deterministic symbol->strategy lookup table for known symbols
3. Enrich the classifier query with proposal/watchlist/strategy_tag data from other tables
4. Re-run dry-run after enrichment to verify the LLM adds value beyond deterministic rules
5. Apply only when classified count > needs_review count

## Safety Confirmation

| Check | Status |
|-------|--------|
| Apply mode run | NO |
| Orders placed | NO |
| Broker writes | NO |
| paper_trades changes | NO |
| Journal/backtest/proposal mutations | NO |
| Qwen used | NO |
| Gemma used | YES |
| Grok called | NO |
| Cron changed | NO |
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
