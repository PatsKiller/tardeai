# Phase 10 — Outcome Learning: close the disposition → learning → calibration loop

Status:      HISTORICAL
as_of:       2026-08-13T20:32:39-04:00
Measured at: efcc51365 / not measured

**"A disposition is durable. A measured outcome is actionable. Wire the second
into the first so the office actually gets smarter."**

## Goal

Phase 9 closed the loop to a durable operator disposition. Phase 10 closes the
final edge of the two-way loop (Phase 5) on the CIO side: a disposition plus a
measured outcome must write BACK into

1. **durable learning candidates** (effect-constrained, never policy/broker/tax), and
2. **reverse-factor sample sizes** (`n` + `evidence_class`) that the scorer's
   reliability gate reads to calibrate reverse weights.

Until now, the reverse edge had a live writer path (`write_realized_outcome`,
`write_options_edge`, `write_hermes_research`) but no CIO-side feeder: nothing
turned `CIOOutcomeStore` records into `n` samples or learning candidates. This
module is that feeder.

## The loop

```
operator disposition  ─┐
measured outcome      ─┼─▶ outcome_signal ─▶ derive_learning_candidates
(POSITIVE/NEGATIVE/…) ─┤                      derive_reverse_writebacks
                      ─┘                      build_calibration
                                  │
                                  ▼
    grade_and_learn() ─▶ CIOOutcomeStore + CIOLearningCandidateStore
                         + reverse writeback directives + calibration
```

## Delivered

| Artifact | Path | Purpose |
| --- | --- | --- |
| Outcome-learning module | `scripts/lib/cio_outcome_learning.py` | pure derivation + `grade_and_learn` orchestrator |
| Dry tests | `tests/test_cio_outcome_learning.py` | 24 tests over normalization, signal, candidates, writebacks, calibration, orchestrator |
| Full-cycle wiring | `scripts/lib/cio_full_cycle.py` | `learning_store` + `grade_and_learn` + `learning` spine + integrity checks |
| CLI | `scripts/cio_full_cycle_dryrun.py` | `--outcome-status` / `--right` / `--wrong` / `--unknowns` / `--symbol` + learning report |
| This document | `docs/investment-office/PHASE10_OUTCOME_LEARNING.md` | scope, semantics, invariants, checkpoint |

## Disposition normalization (one lens, two vocabularies)

Two producers write dispositions — the Phase 8 UI (`decision_dispositions.jsonl`:
`ack`/`defer`/`done`/`reject`) and `CIOOutcomeStore`
(`ACKNOWLEDGED`/`ACCEPTED`/`DEFERRED`/`REJECTED`/`DONE`/`CANCELLED`).
`normalize_disposition()` maps both to one canonical uppercase set. Unknown input
returns `None` and fails closed — no signal is guessed.

## Outcome signal

`outcome_signal(disposition, outcome_status)` returns `hit` / `miss` / `neutral` /
`skip`:

- A measured `outcome_status` is authoritative: `POSITIVE`→hit, `NEGATIVE`→miss,
  `MIXED`→neutral.
- When not yet measurable (`UNKNOWN`/`NOT_MEASURABLE`), the disposition is a
  weaker proxy: agreement (`ACCEPTED`/`DONE`)→hit, `REJECTED`→miss,
  `DEFERRED`→neutral.
- A passive acknowledgement with no measurement → `skip` (no learning invented).

## Learning candidates (effect-constrained)

`derive_learning_candidates()` mints candidates only when the outcome supports
them, each with `proposed_effect` ∈ `CIOLearningCandidateStore.ALLOWED_EFFECTS`:

| Trigger | Effect |
| --- | --- |
| `what_was_wrong` / `NEGATIVE` / `REJECTED` | `confidence_calibration` |
| `what_was_right` + positive/agreed | `retrieval_weighting` |
| `unknowns` | `research_checklist` |
| `REJECTED` | `routing_proposal` |
| `DEFERRED` | `routing_proposal` (follow-up) |
| non-positive result summary | `communication_improvement` |

Forbidden effects (`risk_policy`, `broker_authority`, `tax_strategy`, …) are
rejected by the store, so a candidate can never touch authority.

## Reverse writebacks (the scorer's sample feed)

`derive_reverse_writebacks()` returns *directives* for the existing two-way
writers, not a second write path. A `skip` signal mints nothing. A symbol is
required because every reverse factor folds onto a per-symbol watchlist row.

Evidence class is honest:

- measured outcome (`POSITIVE`/`NEGATIVE`/`MIXED`) → `realized`
- disposition-only proxy → `proxy`

so the scorer's reliability gate never conflates operator agreement with a
realized trade outcome.

## Calibration (reliability-gated weights)

`build_calibration()` wraps `two_way_curation.calibrate_reverse_weights` with the
canonical base weights from `config/hermes_score_weights.yaml` v9
(`thesis_outcome=0.057`, `options_edge=0.045`, `hermes_research=0.055`). Below
`n_min` a factor is damped linearly; at `n=0`/unknown it drops to zero. Effective
weight can never exceed base weight.

## `grade_and_learn` (orchestrator)

Records the outcome to `CIOOutcomeStore`, derives and persists candidates to
`CIOLearningCandidateStore`, derives reverse writebacks, and returns the
calibrated weights — the learning spine from disposition through to calibration.

## Integrity checks added to the Phase 9 spine

- `learning_loop_closed` — outcome recorded (hard).
- `learning_candidates_linked` — each candidate links to its outcome + action
  (hard when candidates exist; else a note).
- `calibration_not_inflated` — no calibrated weight exceeds its base (hard).

## Safety invariants

- `READ_ONLY_ADVISORY` — no broker/order/stop/2FA/provider authority.
- Learning candidates are effect-constrained to `ALLOWED_EFFECTS`; forbidden
  effects are rejected at the store.
- Reverse writebacks are directives; the live governed writers apply them under
  the app role (least privilege), never a new write path.
- Fail-closed: an unmeasured outcome (`skip`) produces no candidates and no
  writebacks.

## Checkpoint 10

```bash
python3 -m pytest tests/test_cio_outcome_learning.py tests/test_cio_full_cycle.py -q
python3 scripts/cio_full_cycle_dryrun.py --disposition REJECTED --outcome-status NEGATIVE \
    --wrong "Overweighted energy ahead of a supply glut" --unknowns "Supply/demand timing" \
    --symbol XOM
```

The graded run shows `learning_loop_closed` + `learning_candidates_linked` passing
with candidates minted and a `thesis_outcome` writeback (n=1, damped below
`n_min`, `trusted=False`), while the default unmeasured run stays fail-closed
(`skip`, 0 candidates, 0 writebacks).

## Phase 10 status

Complete (code + dry tests + full-cycle wiring + CLI + docs). The disposition →
learning → calibration loop is proven in sandbox; the live reverse-factor
backfill (`n` population) remains gated on the operator's Git/release checkpoint,
matching the Phase 5 §8 known-gap note.
