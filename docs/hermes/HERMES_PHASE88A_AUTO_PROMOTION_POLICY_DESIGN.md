# Phase 88A — Auto-Promotion Eligibility Policy

**Date:** 2026-06-01
**Status:** COMPLETE

## Allowed Candidates

- Advisory cache only (hermes_* namespace)
- Cache refresh for already-existing sections
- Source-backed factual updates
- Low-risk context enrichment

## Minimum Thresholds

| Dimension | Threshold |
|-----------|-----------|
| evidence_strength | >= 0.85 |
| source_credibility | >= 0.80 |
| actionability | >= 0.75 |
| freshness | >= 0.75 |
| duplicate_risk | <= 0.20 |
| execution_contamination | = 0 |
| rollback_ready | = true |
| advisory_only | = true |

## Forbidden Forever

- Broker actions, trades, proposals, journal, holdings
- Auto-rebalance, tax/retirement execution
- High-impact thesis reversal without operator review
- Low-confidence research, vague recommendations
- Unsupported catalyst claims

## Daily Caps

- Max 2 auto-promotions/day
- Max 1 new cache section/day (refresh unlimited)

## Operator Override

- Operator can block any auto-promotion via veto file
- Operator can expand/restrict caps via config
