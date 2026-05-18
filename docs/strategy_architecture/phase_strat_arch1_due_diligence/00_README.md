# STRAT-ARCH-1 — Strategy Intelligence Architecture Due Diligence

**Status:** COMPLETE

## Purpose

Deep architecture due diligence based on PAR-1 findings: 22 stale quotes, 70 route
mismatches, momentum_scalp too broad, earnings_post_momentum too loose, YAML
scoring_weights unused, 9 strategies with zero criteria.

## Deliverables

### Architecture Due Diligence

1. **Quote Architecture** (01) — 4 gaps: no proactive refresh, no quality score,
   no fallback alerting, after-hours relaxation too generous
2. **Router Scoring** (02) — 5 gaps: flat scoring, no family gating, primary override
   hides mismatch, no normalization, YAML weights unused
3. **Strategy Taxonomy** (03) — 4 gaps: 9 zero-criteria strategies, no family gating,
   earnings overlap, growth overlap
4. **Evidence Architecture v2** (04) — 4 gaps: no pre-proposal score, no route
   explanation, no performance feedback, no evidence decay
5. **Finviz Architecture** (05) — 5 gaps: naming mismatch, underfilled runs, no
   outcome tracking, no A/B testing, coverage gaps

### Enhancement Roadmap (06)

- **P0 (now):** Wire YAML weights, family gating, quote refresh, screener naming fix
- **P1 (post-A-5):** Weighted scoring, mismatch blocker, criteria expansion, evidence score
- **P2 (live prep):** Normalization, quality score, route explanation, evidence decay
- **P3 (volume):** Performance feedback loop, A/B testing

### Diagnostic Script

`scripts/report_strategy_architecture_diagnostic.py` — surfaces all findings in one report.

## Key Finding

**The single highest-leverage fix is R-5: wire YAML scoring_weights into the router.**
Every strategy already has a `scoring_weights` block with factor weights. The router
ignores it and uses flat +10 per criterion. Connecting this existing design to the
existing code would eliminate the "momentum_scalp always wins" problem without
changing any YAML or strategy activation.

## Tests

15/15 pass, PAR-1 15/15 regression.
