# R18–R23+ forward architecture (source/shadow)

**Authority:** `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0`  
**Branch:** `chore/r18-r22-institutional-intelligence` (off CURRENT)  
**Base:** merged main `2d988c76` (PR #515)  
**Activation:** all OFF  
**R17 live wiring:** not in this branch

Evidence class of this document: **SOURCE_ONLY**.

---

## Operating principle

Engineering may run ahead of evidence. **Activation must never run ahead of evidence.**

Live gates stay sequential:

`canonical universe post-deploy → R17 natural checkpoint/outcome loop → LIVE credit`

The engineering program does not wait for that sequence to start building R18+.

---

## What already exists (reuse, do not fork)

| Piece | Path | Role |
|---|---|---|
| OutcomeObservation, lookahead, bitemporal, lessons, hypotheses, shadow experiments, REVIEW_READY firewall | `scripts/lib/cio_institutional_learning.py` | R16 contracts R18/R19 consume |
| identity-safe subject (never mint GUID from ticker) | `identity_safe_subject` | all rounds |
| checkpoint jsonl + due processor **function** | same module | R17 *implementation exists*; **not enabled** here |
| learning candidate store + forbidden effects | `scripts/lib/cio_learning_candidate.py` | R19 persistence later |
| Canonical universe | `scripts/lib/transferson_universe.py` | R20/R21/R22 denominator |
| Graph edges with provenance | `scripts/lib/ticker_knowledge_graph.py` | R20 paths |
| Free-first labeled as not-universe | `scripts/lib/free_first_circulation.py` | R20 acquisition later |
| Holdings denominator | `scripts/lib/holdings_universe.py` | R21 |

R17 gap register (`docs/_evidence/r16_2/R17_GAP_REGISTER.json`) remains the live-wiring list: scan→checkpoint, cockpit bind, due timer, idempotent generation key. **Those stay Track A.**

---

## Dependency graph

Needs **R17 LIVE** natural `OutcomeObservation`s:

- R18 LIVE calibration (not the contracts)
- R19 LIVE pattern/lesson promotion credit
- R23 causal/cross-regime/decay *rates*

Can be built **immediately** (this branch):

- R18 contracts + cohort math + tiny-sample refusal
- R19 pipeline + firewall mapping onto R16 stages
- R20 impact candidate set over canonical universe
- R21 portfolio cognition (advisory)
- R22 CIO loop slots
- tests / golden-shadow / historical-replay harnesses
- activation switches (all false)

---

## New contracts (this branch)

| Round | Schema | Module |
|---|---|---|
| control | `EvidenceClassGuard@v1` | `cio_forward_program.py` |
| R18 | `CalibrationObservation@v1`, `CalibrationCohort@v1`, `DecisionQualityProfile@v1` | `r18_calibration_fabric.py` |
| R19 | `InstitutionalLearningRecord@v1` | `r19_learning_engine.py` |
| R20 | `ImpactCandidateSet@v1` | `r20_universe_propagation.py` |
| R21 | `PortfolioCognition@v1` | `r21_portfolio_cognition.py` |
| R22 | `InstitutionalCioLoop@v1` | `r22_cio_loop.py` |

Promotion path (R19):

`CANDIDATE → SHADOW → EVALUATED → REVIEW_READY → OPERATOR_AUTHORIZED`

The last step requires a **separate operator authorization**. The engine cannot perform it.

---

## R23+ only where there is a capability boundary

Not invented R-numbers. These cannot be folded into R18–R22 without lying about the contract:

| Stage | Boundary | Input | Output | Prerequisite | Why not R18–R22 | Activation evidence |
|---|---|---|---|---|---|---|
| Causal-hypothesis testing | intervention vs correlation | preregistered experiment + outcomes | causal estimate | R19 REVIEW_READY + LIVE outcomes | R19 is associative/shadow | LIVE experiments |
| Cross-regime learning | parameters must change with regime | regime-tagged outcomes | regime-conditional profile | R18 + regime taxonomy | R18 is pooled | multi-regime LIVE |
| Temporal knowledge decay | validity interval on facts | as_of beliefs + later contradictions | decay function | bitemporal store | R18 cutoff ≠ decay model | elapsed LIVE |
| Evidence-source reliability | source_refs → quality | outcome-linked sources | source weights (candidate) | R18 lane cohorts | lane ≠ source reliability | LIVE source_refs |
| Counterfactual evaluation | what would baseline have done | twin decisions | delta vs actual | R19 holdout | holdout ≠ counterfactual twin | replay + LIVE |
| Opportunity-cost learning | substitution outcomes | R21 substitutes + later results | cost of not rotating | R21 + R17 | cognition ≠ measured cost | LIVE substitution |
| Institutional policy recommendation | operator-authorized policy text | REVIEW_READY record | policy draft | R19 ceiling | engine must not self-authorize | separate operator grant |

No other R-numbers in this tranche.

---

## Activation

`scripts/lib/cio_forward_program.py` `ACTIVATION` is `{R18–R22: false}`.

`gated_live_run(..., evidence_class="LIVE")` returns `LIVE_ACTIVATION_OFF`.

Do not wire these modules into CURRENT crontab, material scan, or R17 persist_checkpoint in this tranche.

---

## Tests

`tests/test_r18_r22_forward.py` — UNIT_TEST / GOLDEN_SHADOW only. No LIVE outcomes fabricated.
