# SP-2 Screener Optimization Design

**Status:** DESIGN ONLY — not implemented. Human-review-only.

## Detection Methods

### Too-Narrow Screeners
- Average symbols per run < 3
- Zero-result runs > 30% of total runs
- Conversion rate > 50% (accepting almost everything — not enough filtering diversity)

### Too-Broad/Noisy Screeners
- Average symbols per run > 200
- Proposal conversion rate < 1%
- High reject rate after quality gates

### Stale/Broken Screeners
- No runs in 7+ days
- Zero-result runs > 50%
- Finviz URL returning errors or empty pages

### Screener Cohort Comparison
- Compare conversion rates across screeners targeting the same strategy
- Flag screeners significantly worse than peers

## Shadow A/B Testing (Future SP-3)

1. Clone existing screener with modified filters
2. Run both screeners in parallel for 2+ weeks
3. Compare candidate quality, proposal conversion, and trade outcomes
4. Require 30+ candidates per variant before drawing conclusions
5. Human approval required before switching

## Threshold Change Process

1. Document current threshold and proposed change
2. State hypothesis and expected improvement
3. Run shadow test for minimum 2 weeks
4. Review results with operator
5. Apply change only with operator approval
6. Monitor for 1 week after change
7. Rollback if degradation detected

## Evidence Requirements

- No screener should be changed based on < 30 candidates of evidence
- No screener should be changed based on < 5 closed trade outcomes
- Statistical significance is not achievable with current trade volume
- All changes are exploratory, not conclusive

## How Results Feed SP-1 and A-5

- SP-2 screener quality feeds SP-1 strategy proof evidence funnel
- Watch horizon state feeds A-5 observation completeness
- Assignment engine audit feeds maturity control board
- All findings are human_review_only inputs to the final A-5 review

## Suggested Future Phase

**SP-3 — Human-Reviewed Screener A/B Shadow Testing**
- Only if SP-2 finds clearly broken or underperforming screeners
- Requires operator approval before any shadow test begins
- Requires minimum 2-week observation before any conclusion
