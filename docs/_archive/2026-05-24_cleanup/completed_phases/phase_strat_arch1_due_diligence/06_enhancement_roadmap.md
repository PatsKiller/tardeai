# STRAT-ARCH-1: Enhancement Roadmap

## Priority Matrix

All items are human_review_only. No implementation without operator approval.

### P0 — Critical (implement before or with final A-5)

| ID | Enhancement | Why | Effort | Risk |
|----|-------------|-----|--------|------|
| R-5 | Wire YAML scoring_weights into router | Already designed, not connected. Eliminates flat +10 bias. | Medium | Low — additive |
| R-2 | Strategy family gating | Prevents cross-family misroutes (intraday vs position). | Low | Low — filter only |
| Q-1 | Scheduled quote refresh for pending proposals | 22 stale + 17 unknown = 47% of proposals have bad quotes. | Medium | Low — read + update quote only |
| F-1 | Fix screener run health naming | Cannot audit screeners without linkage. | Low | None |

### P1 — High (implement after A-5, before live consideration)

| ID | Enhancement | Why | Effort | Risk |
|----|-------------|-----|--------|------|
| R-1 | Per-criterion weighted scoring | Eliminates "more criteria = higher score" bias. | Medium | Medium — changes routing |
| R-3 | Severe mismatch blocker (>20 point gap) | Prevents silent mismatch from reaching approval. | Low | Low — blocker only |
| T-1 | Add entry criteria to 9 zero-criteria strategies | Without criteria they cannot participate in routing. | High | Medium — YAML changes |
| E-1 | Incubator evidence score at promotion | Prevents promotion of candidates with zero evidence. | Medium | Low |
| F-3 | Screener-to-outcome conversion funnel | Required for screener quality optimization. | Medium | None |

### P2 — Medium (implement during live preparation)

| ID | Enhancement | Why | Effort | Risk |
|----|-------------|-----|--------|------|
| R-4 | Score normalization by max possible | Removes criteria-count bias between strategies. | Medium | Medium |
| Q-2 | Quote quality score (0-100) | Better than binary eligible/not. | Medium | Low |
| Q-3 | Provider fallback alerting | Operator visibility into provider failures. | Low | None |
| T-3 | Earnings strategy criteria harmonization | 3 earnings strategies with inconsistent criteria. | Medium | Medium |
| E-2 | Route explanation field | Human-readable routing reasoning. | Medium | None |
| E-4 | Evidence decay model | Stale technical/catalyst should be flagged. | Medium | Low |

### P3 — Low (deferred, requires volume)

| ID | Enhancement | Why | Effort | Risk |
|----|-------------|-----|--------|------|
| E-3 | Performance feedback loop | Requires 20+ closed trades per strategy. | High | High |
| Q-4 | After-hours quote tightening | Only relevant for live trading. | Low | Low |
| F-4 | Screener A/B shadow testing | Requires stable baseline and volume. | High | Medium |
| T-4 | Growth strategy exclusion rules | Low urgency with family gating. | Low | Low |

## Implementation Order (Recommended)

1. **Now (pre-A-5):** F-1 naming fix, R-2 family gating design, Q-1 quote refresh design
2. **With A-5 final:** R-5 YAML weights, R-3 mismatch blocker, E-1 evidence score
3. **Post-A-5:** R-1 weighted scoring, T-1 criteria expansion, F-3 conversion funnel
4. **Live prep:** R-4 normalization, Q-2 quality score, E-2 route explanation
5. **Volume-dependent:** E-3 performance loop, F-4 A/B testing

## Decision Authority

All items require operator approval before implementation.
No auto-optimization. No auto-activation. No trade/order creation.
YAML changes require explicit operator sign-off per strategy.
Router changes require regression validation before deploy.
