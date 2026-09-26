# Options Desk Executive Audit — 2026-09-25

**Scope:** Options Desk v3, strategy engines, recommendation paths, portfolio re-entry, CIO oversight, persistent intelligence, and presentation standards
**Review mode:** source/config/test inspection plus read-only runtime validation plan
**Authority:** `READ_ONLY_ADVISORY`; broker execution and live order paths were not exercised

## Executive conclusion

The platform has a substantial and safety-conscious Options Desk foundation. Strategy configuration, fail-closed eligibility, lifecycle policy, holdings-funnel refusal reasons, re-entry scoring, thesis versioning, and CIO authority boundaries already exist.

The principal institutional gap is not absence of components; it is inconsistent composition. The platform does not yet expose one canonical, recommendation-level comparison that puts direct equity, option structure, capital commitment, maximum risk, expected return, opportunity cost, portfolio impact, thesis continuity, and CIO commentary on the same decision surface.

## Baseline observations

- Options Desk v3 includes Lifecycle, Proposals, Open Options, Strategy Overview, and Options Trends.
- Proposal generation and lifecycle logic are separated into dedicated engines and versioned configuration.
- The holdings funnel explicitly refuses to fake covered calls when fewer than 100 shares are held.
- Re-entry logic is deterministic and fail-closed for stale or missing evidence.
- CIO thesis storage is versioned and marked advisory-only.
- The supplied Command Center snapshot reports 8 ideas, 0 open legs, 1 live-eligible idea, 30 NOGO results, and paper validation at 0/30; these values remain operator-provided snapshot evidence until independently re-observed.

## Priority findings

| Priority | Finding | Risk | Remediation |
|---|---|---|---|
| P0 | No universal stock-versus-options comparison contract. | Operator cannot consistently compare capital, risk, return, and opportunity cost. | Implement the recommendation comparison contract in `OPTIONS_DESK_RECOMMENDATION_SPEC_2026-09-25.md`. |
| P1 | Strategy validation is distributed across registry, engine, lifecycle policy, UI, and paper lanes. | A strategy can appear mature in one surface while evidence is incomplete elsewhere. | Build the validation matrix and require explicit strategy status/evidence. |
| P1 | CIO review status is not uniformly distinct from ensemble/model review. | Model confidence may be mistaken for institutional approval. | Add durable CIO disposition status and evidence references. |
| P1 | Thesis and memory continuity are not guaranteed on every recommendation surface. | Recommendations may lose governing context or become difficult to audit longitudinally. | Propagate thesis pin, evidence refs, freshness, and policy versions. |
| P2 | Freshness/provenance is fragmented. | Stale or modeled data can be mistaken for live market evidence. | Add recommendation-level provenance and freshness summary. |
| P2 | Paper, manual, live-review, and advisory states use overlapping vocabulary. | Operator ambiguity at handoff. | Normalize authority, lifecycle, and execution-mode labels. |

## Implementation roadmap

### Phase 1 — Contracts and evidence

- Add the comparison, provenance, CIO review, and thesis scorecard schemas.
- Build one strategy validation matrix from registry, engine, lifecycle policy, and paper evidence.
- Add fixtures for covered calls, CSPs, protective puts, long options, and vertical spreads.

### Phase 2 — Deterministic decision layer

- Compute matched-horizon stock/options comparisons.
- Normalize maximum-risk, EV, POP, R:R, capital, liquidity, and opportunity-cost calculations.
- Preserve explicit unavailable/blocker states.

### Phase 3 — Command Center presentation

- Add Stock Play, Options Play, Capital Required, Maximum Risk, Expected Return, Risk/Reward, Time Horizon, CIO Commentary, and Preferred Structure sections.
- Show thesis pin, source freshness, modeled/live data source, and review status.
- Keep blocked proposals discoverable and explain why they are blocked.

### Phase 4 — Governance and memory

- Record CIO disposition separately from ensemble validation.
- Add thesis continuity and memory replay tests.
- Verify no cognition path can write behavior fields.

### Phase 5 — Runtime proof and rollout

- Run GET-only served-release probes and fixture-backed UI tests.
- Compare source claims, served behavior, and persistent artifacts.
- Roll out behind an advisory/read-only feature flag; monitor unavailable rates, stale-data rates, comparison completeness, CIO-review coverage, and recommendation consistency.

## Acceptance criteria

The enhancement is ready for implementation sign-off when:

1. Every recommendation class has a canonical stock/options comparison or an explicit `review_required` outcome.
2. Every strategy has documented gates, formulas, lifecycle rules, evidence thresholds, and negative cases.
3. CIO review is visibly distinct from model/ensemble validation.
4. Thesis version, provenance, freshness, and policy versions survive from source to rendered recommendation.
5. Missing or stale data cannot produce a preferred structure or false pass.
6. Unit, API, UI, and memory-partition tests cover all supported strategy families.
7. Validation remains read-only and no live broker or 2FA path is exercised.

## Related artifacts

- [Architecture map](OPTIONS_DESK_ARCHITECTURE_MAP_2026-09-25.md)
- [Recommendation specification](OPTIONS_DESK_RECOMMENDATION_SPEC_2026-09-25.md)
- [Governance and memory audit](OPTIONS_DESK_GOVERNANCE_MEMORY_AUDIT_2026-09-25.md)
- [Options and broker execution flows](../OPTIONS_BROKER_EXECUTION_FLOWS.md)
- [Portfolio re-entry desk](../features/PORTFOLIO_REENTRY_DESK.md)
- [CIO authority](../cio/AUTHORITY.md)

