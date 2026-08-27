# SHFS id=860 Dry-Run Classifier Report — 2026-05-29

## Summary

| Item | Value |
|------|-------|
| Dry-run completed | YES |
| Model used | gemma3:12b |
| Proposed classification | needs_review |
| Confidence | 0.3 |
| Evidence status | Zero enrichment — correct needs_review |
| Apply run | **NO** |
| DB writes | **NO** |
| Operator approval needed | **YES** |

## Classifier Output
- **strategy_id**: needs_review
- **confidence**: 0.3
- **reasoning**: No enrichment data available. Requires review.
- **evidence_used**: [] (none)
- **missing_evidence**: enrichment data
- **requires_review**: true

## Peer-Based Manual Assessment
9/9 comparable peers in the same ER run (sub-$10 micro-cap, 1-day hold, stop_hit, -5%) are classified as `speculative_growth`. SHFS fits this pattern exactly.

**Manual recommendation**: `speculative_growth` with confidence 0.5 (capped due to no direct evidence).

## Recommended Next Action
Operator chooses one of:
1. **Direct SQL apply**: `UPDATE strategy_backtest_trades SET strategy_id = 'speculative_growth' WHERE id = 860` — simplest, completes 3,593/3,593
2. **Enrichment-first**: Add SHFS to ticker_strategy_classifications, then re-run classifier for evidence-backed result
3. **Keep needs_review**: Leave unclassified until more data available

## Files Created
- `docs/atm_lifecycle_v1_2026_05_29/shfs_860_dry_run/PREFLIGHT.md`
- `docs/atm_lifecycle_v1_2026_05_29/shfs_860_dry_run/SHFS_860_PRE_STATE.md`
- `docs/atm_lifecycle_v1_2026_05_29/shfs_860_dry_run/shfs_860_pre_state.json`
- `docs/atm_lifecycle_v1_2026_05_29/shfs_860_dry_run/SHFS_860_DRY_RUN_REVIEW.md`
- `docs/atm_lifecycle_v1_2026_05_29/shfs_860_dry_run/SHFS_860_OPERATOR_APPROVAL_APPLY_PLAN.md`
- `logs/strategy_classifier_shfs_860_dry_run.json`

## Safety Confirmation

| Check | Result |
|-------|--------|
| gemma3:12b used | **YES** |
| gemma3:4b fallback used | NO |
| qwen used | **NO** |
| gemma4 e2b/e4b used | **NO** |
| gemma3:27b GPU used | **NO** |
| Grok called | **NO** |
| Orders placed | **NO** |
| Broker writes | **NO** |
| paper_trades changes | **NO** |
| Proposal mutations | **NO** |
| Journal mutations | **NO** |
| Cron changes | **NO** |
| Health-agent files changed | **NO** |
