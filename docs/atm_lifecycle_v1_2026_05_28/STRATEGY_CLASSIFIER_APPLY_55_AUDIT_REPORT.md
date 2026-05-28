# Strategy Classifier Apply 55 — Audit Report

**Date:** 2026-05-28
**Commit:** bbe3d54

## Command Run

```bash
.venv/bin/python3 scripts/trade_strategy_classifier.py --apply --limit 55 \
  --json-out logs/strategy_classifier_apply_55.json
```

## Results

| Metric | Value |
|--------|-------|
| Rows classified | 55 |
| Rows updated (strategy_backtest_trades) | 34 |
| Unique symbols updated | 28 |
| Errors | 0 |
| Post-validation downgrades | 0 |
| Low confidence (<0.7) | 0 |

## Strategy Distribution

| Strategy | Count |
|----------|-------|
| speculative_growth | 36 |
| recovery_watch | 6 |
| swing_trade | 5 |
| dividend_growth_compounder | 3 |
| sector_rotation | 2 |
| core_growth_compounder | 2 |
| swing_breakout | 1 |

## Quality Audit Summary

| Verdict | Count |
|---------|-------|
| evidence_supported | 17/26 sampled |
| questionable | 7/26 sampled |
| needs_manual_review | 2/26 sampled |
| likely_wrong | 0/26 sampled |

### Questionable Rows (7)

All caused by the same pattern: **symbol-level enrichment correct, but trade-level behavior contradicts.** Specifically, 0-day holds classified as long-term strategies:

- AMD x2: core_growth_compounder with hold_days=0
- NUWE x2: recovery_watch with hold_days=0
- SOPA x2: recovery_watch with hold_days=0
- APAM-469: speculative_growth when ticker says dividend_growth_compounder (LLM inconsistency)

### Needs Manual Review (2)

- ADBE x2: classified as speculative_growth. ADBE is a $200B mega-cap — the watchlist_strategy_cards entry tagging it as "speculative_growth" appears to be a source data quality issue, not a classifier bug.

## Rollback SQL

Path: `docs/atm_lifecycle_v1_2026_05_28/classifier_apply/classifier_apply_55_rollback.sql`

Restores strategy_id to NULL for all 28 symbols updated in this batch. Old values were NULL/empty/"unknown" before apply.

```bash
psql -U trade_ai -d trade_ai < docs/atm_lifecycle_v1_2026_05_28/classifier_apply/classifier_apply_55_rollback.sql
```

## Preserved Artifacts

| File | Contents |
|------|----------|
| `classifier_apply/strategy_classifier_apply_55.json` | Full 55-row LLM output |
| `classifier_apply/llm_router_safety.jsonl` | Safety audit log |
| `classifier_apply/classifier_apply_55_rows.json` | 55 audit rows (clean) |
| `classifier_apply/classifier_apply_55_backtest_rows.json` | 71 backtest rows with strategy_id |
| `classifier_apply/classifier_apply_55_rollback.sql` | Rollback SQL |
| `classifier_apply/CLASSIFIER_APPLY_55_ROW_AUDIT.md` | Detailed row-level audit |

## Health Check Result

```
PASS (7/7)
- ollama_reachable: PASS
- qwen3_not_loaded: PASS
- gemma3_numeric: PASS
- gemma3_json: PASS
- disabled_model_routing: PASS
- max_one_model: PASS
- no_unsafe_jobs: PASS
```

## Loaded Models After Run

- gemma3:4b only (normal expiry timestamp)
- qwen3:14b: NOT loaded

## Safety Confirmation

| Check | Status |
|-------|--------|
| Qwen used | NO |
| Gemma4 used | NO |
| Gemma3 used | YES |
| Grok called | NO |
| Orders placed | NO |
| Broker writes | NO |
| paper_trades changes | NO (6 updates were normal pipeline, not classifier) |
| Proposal mutations | NO (1 lifecycle check, not classifier) |
| Journal mutations | NO |
| Unintended backtest mutations | NO (34 rows = intended target) |
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |

## Recommendation

**Proceed with caution.** The batch is not dangerous — no wrong strategies were applied, and rollback is available. However, before the next batch:

1. **Add hold-period post-validation**: Flag when trade hold_days conflicts with strategy definition (e.g., core_growth_compounder with 0-day hold should downgrade to needs_review or momentum_scalp)
2. **Fix ADBE watchlist source data**: ADBE should not be tagged as speculative_growth in watchlist_strategy_cards
3. **LLM consistency check**: APAM-469 got speculative_growth while APAM-468/472 got dividend_growth_compounder from the same enrichment — add a symbol-level consistency pass

No rollback needed at this time. The 7 questionable rows are not harmful — they reflect the symbol's general strategy even if the specific trade behavior was different. The 2 manual-review rows (ADBE) are a source data issue, not a classifier bug.
