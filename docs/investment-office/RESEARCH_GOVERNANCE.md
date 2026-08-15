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
RGA-2  provenance_state_coherent
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

R1 splits acceptance into three disjoint collections:

- `required_runtime` — RGA-1..10, 13, 14 (golden vectors + fail-closed behavior).
- `required_contract` — RGA-11 (promotion-gate contract) and RGA-12 (retrieval
  contract). These must ALSO pass: a broken contract-only gate still fails R1.
- `not_in_scope` — RGA-15 (R3) and RGA-16 (R4); NEVER counted as a PASS.

Overall PASS requires EVERY required_runtime gate to pass AND EVERY
required_contract gate to pass. `R2_mechanics` inherits the R1 foundation and
adds R2A-1..R2A-15 (fixed-income / ETF / valuation mechanics). R3/R4 remain
out of scope.

## Trial registry

`trial_registry.py` enforces the anti-gaming invariant: freeze binds a
PREDETERMINED variant universe (`planned_trial_ids` + `planned_config_hashes` +
`protocol_hash`; confirmatory families additionally require
`family_definition_hash`). Trial records are immutable; selection is an
append-only event with unique ids pointing at a RECORDED (executed) trial, and
conflicting dispositions are surfaced explicitly (never silently resolved).
`result_hash` hashes the actual result artifact:

- inline payloads are hashed by the registry;
- external artifacts require `result_artifact_ref` + `result_artifact_size` +
  `hash_algorithm=sha256` and an injectable `ArtifactVerifier`; the verification
  result (`VERIFIED`/`UNVERIFIED` + `result_verified_at`) is RETAINED on the
  record. A confirmatory `COMPLETED` trial must be `VERIFIED` and carry full
  execution lineage (`code_sha`, `dataset_hash`, `started_at`, `completed_at`).

Terminal dispositions `INVALID` / `FAILED` / `CANCELED_WITH_REASON` require a
`terminal_reason` (+ optional `failure_stage`); completeness means EVERY planned
variant has a terminal disposition and every non-COMPLETED variant has a reason.

OOS windows are immutable and separate two concepts: **economic segment
identity** (`dataset_id` + segment + protocol family) from **dataset snapshot
lineage** (`dataset_hash`). A consumed economic segment cannot become fresh by
changing the snapshot; corrected data is classified `CORRECTED_DATA_RERUN`,
never a fresh untouched OOS generation. The first `oos_consumed_at` is
immutable. Persistence is in-process and immutable; durable append-only
persistence is deferred to a later PR.

## Scope guard

`pr_scope_guard.py` enforces the R1 allowlist against
`git diff --name-only BASE_SHA...HEAD`. Off-limits CIO/retrieval/release files
fail the guard.

## Source catalog

Single canonical data file `config/cio_research_source_catalog.json`, loaded by
`source_catalog.py` with a parity/hash and exact-manifest report. The manifest
matches the governing master canon:

- **20 institutional canon books** — Core Ten (Malkiel, Graham/Zweig, Housel,
  Bogle, Ferri, Thau, Harris, McMillan, Natenberg, Aronson) + #11–#20 (López de
  Prado AFML, Ilmanen, Grinold/Kahn, Damodaran, Marks, Hull, Tuckman/Serrat, Lo,
  Schilit/Perler, **Expectations Investing**).
- **1 separately governed practitioner/seasonality source** — Stock Trader's
  Almanac (not a substitute for institutional book #20).
- **13 primary research papers** — including Sullivan–Timmermann–White's
  *Dangers of Data Mining: The Case of Calendar Effects in Stock Returns*
  (required to challenge Almanac/calendar claims) alongside their
  trading-rule/bootstrap paper.

Provenance honesty is STATE/PROVENANCE coherent, not "everything is permanently
missing": a source lacking lawful full text must carry
`full_text_status=NOT_FOUND_IN_FILE_LIBRARY` AND
`claim_status=SOURCE_CLAIM_INCOMPLETE`. A source that later acquires lawful full
text must instead provide a location/reference, a source hash, a permitted
license class, and a `verified_at` timestamp.

## Reference materials

Formulas independently reimplemented from (not copied wholesale from):

- Bailey & López de Prado (2014), *The Deflated Sharpe Ratio* (SSRN 2460551).
- Bailey, Borwein, López de Prado & Zhu (2015/2017), *The Probability of Backtest
  Overfitting* (SSRN 2326253).
- White (2000), *A Reality Check for Data Snooping*, Econometrica.
- Sullivan, Timmermann & White (1999), *Data-Snooping, Technical Trading Rule
  Performance, and the Bootstrap*, Journal of Finance.
- Sullivan, Timmermann & White (2001), *Dangers of Data Mining: The Case of
  Calendar Effects in Stock Returns*, Journal of Econometrics.
- López de Prado (2018), *Advances in Financial Machine Learning*, Wiley
  (purging / embargo / CSCV, Chapter 12).

## Primary-source validation

Each method's primary source, formula/contract, implementation choice, and any
Trade AI deviation are documented so a non-paper detail is never misattributed
to the paper.

| method | primary_source | formula_or_contract | implementation_choice | deviation_or_extension | reason | known_limitation |
| --- | --- | --- | --- | --- | --- | --- |
| Deflated Sharpe Ratio (DSR/PSR) | Bailey & López de Prado (2014), SSRN 2460551 | `SR* = mu + sigma·maxZ`; PSR denominator-square validated before `sqrt` | Acklam inverse-normal CDF; raw-Pearson kurtosis | None | stdlib-only | skew/kurtosis degenerate ⇒ `UNAVAILABLE` |
| PBO / CSCV | Bailey, Borwein, López de Prado & Zhu (SSRN 2326253) | CSCV over `C(S, S/2)` IS/OOS splits; `omega = avg_rank/(N+1)` | average-rank ties; full enumeration default; reservoir-sampled approximation | tie policy + safe-limit `COMPUTATION_INFEASIBLE` are Trade AI policy, not paper | anti-gaming / resource guard | zero-variance Sharpe is `UNAVAILABLE`, not 0 |
| White Reality Check | White (2000), Econometrica | recentered `V* = sqrt(n)·max mean(f*)` under the null | stationary bootstrap, shared index across rules | `p = (count+1)/(B+1)` + MC resolution floor are Trade AI policy | conservative p | block length ≥ 1 required |
| Calendar data-mining | Sullivan, Timmermann & White (2001), J. Econometrics | whole searched family test, never winner-only | named calendar families | None | challenge Almanac claims | pre/post-publication may be `DATA_UNAVAILABLE` |
| Purged / embargoed CV + CPCV | López de Prado (2018), AFML Ch. 12 | purge label overlap; embargo post-test boundary; combinatorial splits | `combinatorial_purged_splits()` (split generation) | CPCV PATH construction deferred to a later PR | R1 scope | path/backtest-path layer not yet built |

## Authority boundary

Every promotion terminates in READ_ONLY_ADVISORY. No provider calls, no broker
calls, no production DB writes, no change to live Alex behavior in R1.

