# R-5 — Wire YAML Scoring Weights into Router

**Status:** COMPLETE

## What Changed

`multi_setup_router.py::evaluate_strategy_match()` now uses YAML `scoring_weights`
instead of flat +10 per criterion. Each matched criterion adds its configured
factor weight. Bonuses (price_range, rvol, catalyst) also use YAML weights.

### Key Details

- **9 strategies** have scoring_weights (total 55-100 per strategy)
- **14 strategies** fall back to DEFAULT_CRITERION_WEIGHT=10 (no scoring_weights block)
- Scores normalized to 0-100 with floor at max_possible=50 to prevent bonus-only inflation
- New match thresholds: ≥60 STRONG, ≥35 MODERATE, ≥15 WEAK, <15 NO_MATCH
- Route audit includes: scoring_model_version, scoring_weights_used, raw_weighted_score, max_possible

### Criterion → Factor Mapping

Entry criterion IDs (e.g., `CATALYST_VERIFIED`, `RVOL_SURGE`) are mapped to
scoring_weights factor names (e.g., `catalyst`, `rvol`) via `_criterion_to_factor()`.
Unknown criteria fall back to factor `general` which uses DEFAULT_CRITERION_WEIGHT.

## Shadow Comparison Results

| Metric | Old Flat | New Weighted |
|--------|----------|-------------|
| Top distribution | earnings_post_momentum: 72/81 | momentum_scalp: 69, gap_and_go: 11, swing_trade: 1 |
| earnings_post_momentum domination | Yes (89%) | **Eliminated** |
| Top match changed | — | 78/81 (96%) |

`earnings_post_momentum` no longer dominates. Distribution is more realistic
for the candidate types (mostly small-cap momentum/gap candidates).

## Tests

15/15 R-5 + SP-2C 17/17 + SP-2B 17/17 regression.
