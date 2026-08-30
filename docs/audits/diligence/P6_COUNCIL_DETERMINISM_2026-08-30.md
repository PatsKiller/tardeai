# P6 — CIOCouncilSynthesis determinism

**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY  
**MBI_BEHAVIOR:** 0  
**Package:** Diligence Phase 6 (master plan § PHASE 6)

## Claim

`CIOCouncilSynthesis@v1` is a **deterministic join**, not a model council. Same
inputs produce the same synthesis fields; disagreement is labelled `DISPUTED`
and never silently resolved; non-VALID specialists are excluded with an
explicit `excluded_non_valid` ledger (no silent drop).

## Code under audit

| Artifact | Path |
|----------|------|
| Join | `scripts/lib/cio_council_synthesis.py` |
| Wave 3B baseline tests | `tests/test_cio_wave3b_council_policy.py` |
| P6 property suite | `tests/test_cio_diligence_p6_council_determinism.py` |

## Cases exercised

| Case | Expected `state` |
|------|------------------|
| bullish-only (2+ VALID same stance) | `AGREED` |
| bearish-only | `AGREED` |
| mixed / conflicting specialists | `DISPUTED` (+ `disputed_note`, all ids retained) |
| single VALID | `SINGLE_SOURCE` |
| missing / FAIL / SKIP / execution_language | counted in `excluded_non_valid`; not in `artifact_ids` |
| incomplete research (no explicit position) | positions empty; stance **not** inferred from prose |
| empty artifact list | `NO_VALID_ARTIFACTS` |

## Determinism rule

- With `_utc` frozen, full block equality holds (including `as_of`).
- Without freeze, all fields except `as_of` are stable across repeats.
- `model_called`, `mints_plan`, `attaches_plan`, `financial_action` remain false.

## Rails

No Telegram. No notify-on. No broker / size influence. Reuses Wave 3B; does not
fork a second decision brain.

## Exit gate

**PASS** when `tests/test_cio_diligence_p6_council_determinism.py` is green and
Wave 3B council pins remain green.
