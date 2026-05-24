# SP-2 Scope — Strategy Watch Horizon and Finviz Screener Audit

## Purpose

SP-2 adds read-only strategy watch-horizon governance and Finviz screener quality
auditing. It proves whether the upstream pipeline (screeners, incubator, strategy
routing) is intelligently selecting and watching the right tickers.

## Strategy Proof vs Strategy Optimization

- **Strategy proof** (SP-1/SP-2): Evidence that the system is working correctly.
  Read-only reporting, no changes.
- **Strategy optimization** (future SP-3+): A/B testing screener changes,
  threshold adjustments. Requires human approval, shadow testing, rollback.

SP-2 is strategy proof only. It produces evidence and recommendations but does
not auto-apply anything.

## Watch Horizon Concept

Different strategies need different observation periods before a ticker is ready
for proposal. momentum_scalp may act same-day. recovery_watch may need 5-20
trading days of observation. dividend_growth_compounder may need 30-180 days.

SP-2 defines strategy-specific watch windows and classifies each candidate's
maturity state: new, observing, maturing, ready, expired, disqualified.

## Finviz Screener Quality Concept

18 Finviz screeners feed the pipeline. SP-2 audits whether each screener is:
healthy, too narrow, too broad, noisy, stale, underfilled, or broken. It tracks
screener → candidate → proposal → trade → outcome conversion rates.

## Relationships

- **SP-1**: Evidence funnel and proof status per strategy. SP-2 extends upstream.
- **PP-UX-2**: Trust audit per proposal. SP-2 audits the pipeline before proposals.
- **A-5**: Observation window ends 2026-05-22. SP-2 findings feed A-5 review.

## What SP-2 Adds

- Strategy watch horizon policy (pure functions)
- Watch horizon report (per-candidate maturity state)
- Finviz screener quality audit (conversion rates, health status)
- Strategy assignment engine audit (YAML/DB consistency, route evidence)
- Screener optimization design document (human-review-only)

## What SP-2 Must Not Change

- Strategy activation
- YAML thresholds
- Finviz screener configs
- Approval gates
- Execution logic
- Trade creation / order submission
- SP-1 proof policy (except read-only imports)

## Human-Review-Only Policy

All recommendations produced by SP-2 are human_review_only. No auto-optimization.
No screener should be changed based on 1-3 trades of evidence.
