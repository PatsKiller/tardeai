# Research Governance — PR-R1 Foundation

Parallel workstream: book/research knowledge infusion. Isolated from the
production-hardening CIO remediation agent.

- branch: `feature/research-governance-v1`
- worktree: `/home/johnclaw/tradeai-wt-research-governance`
- base: see `RESEARCH_GOVERNANCE_BUILD_BASELINE.md`
- authority: `READ_ONLY_ADVISORY` — nothing here grants broker/order/stop authority.

## Purpose

Govern the promotion of research knowledge (books, primary papers, reproduced
factors, seasonality) into Trade AI cognition so that a weak finding cannot be
promoted merely because its source "sounds right". The methodology books (Aronson,
López de Prado, White, Harvey/Liu/Zhu) have the authority to **block** weak
research promotion; they can never generate a trade.

## Core invariants

```text
NO CONFIRMATORY RESULT WITHOUT A FROZEN HYPOTHESIS FAMILY
NO FROZEN FAMILY WITHOUT A COMPLETE TRIAL REGISTRY
NO COMPLETE TRIAL REGISTRY THAT RECORDS ONLY SELECTED/WINNING VARIANTS
```

Once a confirmatory OOS segment is examined and then used to alter parameters,
that segment is **consumed** (`oos_consumed_at`). It cannot remain untouched OOS
evidence; a later iteration needs a new segment or must be labelled
`POST_OOS_TUNED` rather than `OOS_SUPPORTED`.

## Three orthogonal schema dimensions

Never collapse into one field:

- `evidence_type` — what kind of knowledge (SOURCE_NARRATIVE, DETERMINISTIC_MECHANICS,
  EMPIRICAL_STRATEGY, EMPIRICAL_FACTOR, SEASONALITY, VALUATION_MODEL, ...).
- `research_status` — lifecycle position (SOURCE_CLAIM → ... → OOS_SUPPORTED).
- `evidence_grade` — type-aware quality grade (A/B/C/D/X).

## Statistical governance (applicability-driven)

Each method is validated against GOLDEN reference vectors, not just value ranges:

- **DSR** (`deflated_sharpe.py`) — `mu + sigma*maxZ` (trial-distribution mean is
  part of the benchmark; translation-invariant). Requires a known, consistent
  trial count; otherwise UNAVAILABLE.
- **PBO/CSCV** (`pbo.py`) — OOS rank `1 = worst, N = best`; requires >= 2
  configurations; otherwise NOT_APPLICABLE.
- **White Reality Check / STW** (`bootstrap_reality_check.py`) — null-centered
  (recentered) stationary bootstrap with `sqrt(n)` scaling; one family test.
- **Multiple testing** (`multiple_testing.py`) — Bonferroni, Holm, BH-FDR with
  strict input validation (malformed p-values/alpha fail closed).
- **Purged/embargoed CV + CPCV** (`cv.py`) — separate `purged_walk_forward`,
  `purged_kfold`, and full `combinatorial_purged_cv`; embargo removes only
  post-test training samples.

## Promotion ladder (RG-0 .. RG-11)

`promotion_gate.py` defines the asymmetric, TYPE-AWARE ladder:

```text
RG-0  source_registered
RG-1  source_claim_complete
RG-2  hypothesis_frozen          (empirical only)
RG-3  reproducible               (empirical only)
RG-4  in_sample_reproduced       (empirical only)
RG-5  oos_supported              (empirical only)
RG-6  multiple_testing_applied   (empirical only)
RG-7  reality_check_passed       (empirical only)
RG-8  robust                     (empirical only)
RG-9  graded_and_influence       (shared; grade + influence + no authority)
RG-10 decision_use_audit         (contract-only in R1; live in R4)
RG-11 live_degradation_retirement(contract-only in R1; live in R4)
```

Type-specific requirements replace the empirical ladder for non-empirical facts:
a deterministic bond-duration formula must not be forced through a fake Reality
Check; a policy/tax rule needs jurisdiction and effective date, not a Sharpe
ratio; a valuation model needs assumption provenance and scenario sensitivity,
not a fake CSCV.

Grade ceiling (never bypassable): A/B → `CIO_CONTEXT_ELIGIBLE`; C →
`EXPLORATORY_SHADOW`; D → `SOURCE_ONLY`; X → `INVALIDATED`.

## Subsystem acceptance (RGA-1 .. RGA-16)

`acceptance.py` defines phase-aware acceptance with `PASS / FAIL / NOT_IN_SCOPE`.
`NOT_IN_SCOPE` never counts as PASS. Canonical mapping:

```text
RGA-1  source_registry_exact_manifest
RGA-2  provenance_complete
RGA-3  lifecycle_grade_separated
RGA-4  trial_registry_frozen_complete
RGA-5  no_lookahead_contract
RGA-6  multiple_testing_validated
RGA-7  deflated_sharpe_golden
RGA-8  pbo_golden
RGA-9  reality_check_golden
RGA-10 cv_purging_golden
RGA-11 promotion_gate_contract
RGA-12 retrieval_contract
RGA-13 authority_boundary
RGA-14 scope_guard
RGA-15 almanac_reproduction             (R3)
RGA-16 research_decision_use_audit      (R4)
```

R1 requires RGA-1..10, 13, 14; RGA-11/12 are contract-only; RGA-15/16 are not in
scope until R3/R4.

## Trial registry

`trial_registry.py` enforces the anti-gaming invariant: freeze binds a
PREDETERMINED variant universe (`planned_trial_ids` + `planned_config_hashes` +
`protocol_hash` + `family_definition_hash`). Trial records are immutable;
selection is an append-only event; `result_hash` hashes the actual result
artifact (no parameter-hash fallback); completeness means EVERY planned variant
has a terminal disposition; the first `oos_consumed_at` is immutable.

## Scope guard

`pr_scope_guard.py` enforces the R1 allowlist against
`git diff --name-only BASE_SHA...HEAD`. Off-limits CIO/retrieval/release files
fail the guard.

## Source catalog

Single canonical data file `config/cio_research_source_catalog.json` (20 books +
12 primary research papers), loaded by `source_catalog.py` with a parity/hash and
exact-manifest report. Missing full text is honestly recorded as
`NOT_FOUND_IN_FILE_LIBRARY`; unread sources remain `SOURCE_CLAIM_INCOMPLETE`.

## Reference materials

Formulas independently reimplemented from (not copied wholesale from):

- Bailey & López de Prado (2014), *The Deflated Sharpe Ratio* (SSRN 2460551).
- Bailey, Borwein, López de Prado & Zhu (2017), *The Probability of Backtest
  Overfitting* (SSRN 2326253).
- White (2000), *A Reality Check for Data Snooping*, Econometrica.
- Sullivan, Timmermann & White (1999), *Data-Snooping, Technical Trading Rule
  Performance, and the Bootstrap*, Journal of Finance.
- López de Prado (2018), *Advances in Financial Machine Learning* (purging /
  embargo / CPCV).

## Authority boundary

Every promotion terminates in READ_ONLY_ADVISORY. No provider calls, no broker
calls, no production DB writes, no change to live Alex behavior in R1.
