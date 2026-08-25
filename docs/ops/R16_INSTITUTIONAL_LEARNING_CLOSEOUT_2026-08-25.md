# R16 — Institutional learning closeout

**Date:** 2026-08-25  
**Authority:** READ_ONLY_ADVISORY · `MEMORY_BEHAVIOR_INFLUENCE=0`  
**Canary:** unset · **Cash:** unconfirmed

## Pins (do not confuse)

| | SHA |
|---|---|
| repository_head (after #510) | `ce105e65cbaca23f839f95a7540f93f8033745ae` |
| runtime_source (CURRENT) | `d72ecdd13d4fad1e7551597634f326aeb6a03353` |
| exact_runtime_release | `d72ecdd1-main-exact-phase2-20260825-120222` |

PR #510 was docs-only. **No redeploy.** Docs-on-main vs R15.2-on-CURRENT is expected, not a pin alarm.

## What R16 added (source)

Learning contracts, not another brain:

- `OutcomeObservation@v1` append-only, multi-horizon
- quality axes independent of P&L
- confidence calibration that ignores model self-score
- `LessonCandidate@v2` with counterexample search; one outcome ≠ methodology
- preregistered `HypothesisCandidate` + control/candidate shadow experiments
- lookahead firewall (zero tolerated future leaks)
- promotion stages through `REVIEW_READY` only; no self-approve
- notification learning and operator feedback as evidence, not policy
- Learning cockpit GUI projection (`cio-brain-learning-cockpit`)

## Live historical coverage (honest)

- 5 live scan/disposition rows: all `PARTIAL` (missing `security_guid`)
- 25 `OUTCOME_RECORDED` events on CURRENT: linked by `cio_action_id`, not security GUID
- `FULLY_TRACEABLE`: 0 — joins were **not** fabricated
- Calibration / specialist scores: GOLDEN_SHADOW
- ModelTaskPerformance: LIVE=0, HISTORICAL_REPLAY=300, GOLDEN_SHADOW fills sparse cohorts
- Routing candidates: 0; registries unchanged
- NATURAL_LONGITUDINAL improvement: none

## Tests

R16 suite 400+ passed (outcome/lookahead/specialist goldens, property, faults, live-shaped integration).

## Maturity

**Runtime operating maturity remains 86** (R15.2 on CURRENT).  
R16 learning subsystem is **source/unit proven**; not deployed. **88–90 not awarded.**

Do not treat undeployed R16 as live intelligence.
