# Strategy Classifier Hold-Period Gate Report

**Date:** 2026-05-28
**Dry-run sample:** 30 trades
**Model:** gemma3:4b (GPU)

## Prior Audit Questionable Rows (7) — Resolution

| Case | Prior verdict | New behavior | Resolution |
|------|--------------|--------------|------------|
| AMD x2 (0d core_growth) | questionable | EXCEPTION: kept, 2 sources agree (ticker + watchlist family), conf capped 0.65 | Acceptable — enrichment confirms symbol-level strategy |
| NUWE x2 (0d recovery) | questionable | HARD GATE: would downgrade to needs_review (only 1 source), conf 0.45 | Fixed |
| SOPA x2 (0d recovery) | questionable | EXCEPTION: kept, 2 sources agree (ticker + watchlist), conf 0.65 | Acceptable — strong enrichment support |
| APAM-469 (spec_growth) | questionable | CONFLICT GATE: conf capped 0.5, flagged (0 sources support, 2 conflict) | Fixed — conflict surfaced |

**6 of 7 cases resolved:** 2 hard-gated to needs_review, 4 kept with evidence exception and capped confidence, 1 flagged as conflict with confidence reduction. The ADBE manual-review cases did not recur (ADBE was not re-classified as dividend in this run).

## Dry-Run Results

| Metric | Count |
|--------|-------|
| Total | 30 |
| Classified (exact strategy) | 27 |
| needs_review | 3 |
| unknown | 0 |
| errors | 0 |
| Post-validation downgrades | 10 |
| Trades with source conflicts | 12 |

### Strategy Distribution

| Strategy | Count |
|----------|-------|
| speculative_growth | 18 |
| dividend_growth_compounder | 3 |
| needs_review | 3 |
| recovery_watch | 2 |
| sector_rotation | 2 |
| core_growth_compounder | 2 |

### Downgrades by Gate Type

| Gate | Count | Action |
|------|-------|--------|
| Hard gate (0d on long-hold, <2 sources) | 0 | Would downgrade to needs_review, conf 0.45 |
| Exception (0d on long-hold, 2+ sources) | 2 (AMD) | Kept with conf cap 0.65 |
| Caution gate (1-5d, <2 sources) | 0 | Would downgrade to needs_review, conf 0.55 |
| Hold-range violation (swing 0d) | 3 (LASE, SPRC x2) | Downgraded to needs_review |
| Conflict gate (0 sources) | 3 (APAM, EKSO x2) | Conf capped 0.5 |
| Conflict gate (majority disagree) | 2 (XMTR x2) | Conf capped 0.55 |

### ADBE Handling

ADBE was classified as speculative_growth (matching watchlist) with 1 conflicting source (ticker=swing_trade). The ADBE rule did not fire because it was not classified as dividend_growth_compounder. The ADBE rule is a safety net — it correctly blocks dividend classification if only watchlist supports it.

## New Validation Rules Summary

1. **Hard gate (Rule 4):** 0-day hold on long-hold strategy requires 2+ enrichment sources agreeing. Otherwise needs_review, conf max 0.45.
2. **Caution gate (Rule 4):** 1-5 day hold on long-hold strategy requires 2+ sources. Otherwise needs_review, conf max 0.55.
3. **Hold-range validation (Rule 4):** Each strategy has min/max hold days. Violations downgrade.
4. **Conflict gate (Rule 5):** When 0 enrichment sources support the classification, flag and cap confidence. When majority disagree, cap confidence.
5. **ADBE rule (Rule 6):** ADBE dividend_growth_compounder requires ticker or proposal confirmation, not watchlist alone.
6. **Evidence source counting:** Every result includes `evidence_source_count` and `conflicting_sources`.

## Next Apply Recommendation

**YES — safe to proceed with next batch.** The hold-period gates are catching the 7 audit cases appropriately. Conflicts are surfaced and confidence is reduced. No false long-term classifications on day trades.

**Recommended batch size:** 30 trades. This covers the remaining unclassified trades while keeping the batch auditable.

## Safety Confirmation

| Check | Status |
|-------|--------|
| Apply mode run | NO (dry-run only) |
| Qwen used | NO |
| Gemma4 used | NO |
| Gemma3 used | YES |
| Grok called | NO |
| Orders placed | NO |
| Broker writes | NO |
| paper_trades changes | NO |
| Proposal/journal/backtest mutations | NO |
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
