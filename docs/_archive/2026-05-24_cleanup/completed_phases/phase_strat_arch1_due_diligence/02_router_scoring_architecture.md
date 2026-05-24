# STRAT-ARCH-1: Router Scoring Architecture Due Diligence

## Current Scoring Model

Pure additive: entry criteria (+10 each) + RVOL (+15) + price range (+5/+5) + catalyst (+10/+5).
Match thresholds: ≥50 STRONG, ≥30 MODERATE, ≥10 WEAK, <10 NO_MATCH.
Disqualifiers hard-block (BLOCKED status, not a penalty).
Primary strategy = proposal's assigned strategy_id (always marked primary regardless of score).
Secondaries ranked by score.

## Why momentum_scalp Wins Too Broadly

momentum_scalp has 3 entry criteria → 30 base points if all met.
Add RVOL (+15), price range (+10), catalyst (+10) → 65 possible.
Its criteria are broad: RVOL_SURGE (rvol ≥ 2), PRICE_RANGE ($1-$25), ENTRY_WINDOW (market hours).
Most small/mid-cap candidates with any volume spike match at least 2-3 criteria → 20-35 points → MODERATE_MATCH.
There are only 1 disqualifier (LOW_FLOAT_EXTREME).

**Root cause:** momentum_scalp has the broadest price/RVOL criteria of any strategy and few disqualifiers.

## Why earnings_post_momentum Scores 45 Frequently

earnings_post_momentum has 3 criteria → 30 base.
Its price range is broad ($5-$500). Float tolerance is huge (500M).
When 3/3 criteria + price (+10) + catalyst (+5) = 45.
Even with 1 miss: 20 + 10 + 5 + 10 = 45 (MODERATE).
It scores well for anything with recent earnings + gap up.

## Architecture Gaps

### Gap R-1: Flat Scoring Without Strategy Specificity
All criteria are worth +10 regardless of importance. A catalyst match is worth
the same as a price-range match. This means strategies with broad, easy-to-match
criteria always outscore strategies with narrow, hard-to-match criteria.

**Recommended fix:** Allow per-criterion weights in YAML (already has `scoring_weights`
block, not used by router). Router should read weights instead of flat +10.

### Gap R-2: No Mutual Exclusion Between Strategy Families
INTRADAY strategies (momentum_scalp, gap_and_go) compete with POSITION strategies
(dividend_growth_compounder) on the same scoring scale. A micro-cap day trade
should never route to a dividend compounder, but without family gates it could.

**Recommended fix:** Strategy family gates: evaluate INTRADAY candidates only against
INTRADAY strategies, MULTI_DAY against MULTI_DAY, etc. Use timeframe_class or bucket.

### Gap R-3: Primary Strategy Override Hides Mismatch
The router always marks the proposal's original strategy_id as primary, even if
it has the lowest score. This means the "trust audit" shows a mismatch but the
proposal proceeds as if the original assignment is correct.

**Recommended fix:** If router top match differs from assigned strategy by >20 points,
flag as `strategy_mismatch_severe` and require human review before approval.

### Gap R-4: No Score Normalization
A strategy with 5 criteria can score 50+bonuses = 80 max, while a strategy with
2 criteria can score 20+bonuses = 45 max. This inherently biases toward strategies
with more criteria.

**Recommended fix:** Normalize scores by max possible per strategy, then compare
percentages. 80% of a 5-criteria strategy = 90% of a 2-criteria strategy in
normalized terms.

### Gap R-5: YAML scoring_weights Block Is Unused
Every YAML has a `scoring_weights` section with strategy-specific factor weights.
The router ignores it entirely and uses flat +10.

**Recommended fix:** Wire YAML scoring_weights into the router. This is the
highest-leverage fix — it's already designed, just not connected.

## Priority

| Gap | Severity | Effort | Safe now? | Depends on A-5? |
|-----|----------|--------|-----------|-----------------|
| R-5 | Critical | Medium | Design only | No |
| R-1 | Critical | Medium | Design only | No |
| R-2 | High | Low | Design only | No |
| R-3 | Medium | Low | Yes (blocker) | No |
| R-4 | Medium | Medium | Design only | No |
