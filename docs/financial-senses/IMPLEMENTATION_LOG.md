# Implementation log

Status:      ACTIVE
as_of:       2026-08-17T13:10:42-04:00
Measured at: efcc51365 / not measured

Timestamps in UTC-4 (local). Updated after every phase.

## 2026-08-16 — Phase 0 (preflight + inventory)

- base SHA: `968dafb6beda21aa11aa4cedeb7c9c3920c3fec4` (fresh `origin/main`, PR #339 merged)
- base source: `origin/main`
- branch: `feature/financial-senses-parallel-v1`
- worktree: `/home/johnclaw/tardeai-financial-senses-parallel-v1`
- other active worktree: `/home/johnclaw/tradeai-wt-cio-decision-truth`
  (`feature/agent-intelligence-foundation`)
- collision audit: other branch touches only `docs/agent-intelligence/**`,
  `scripts/lib/agent_*.py`, `tests/test_agent_*.py` — no overlap with the
  `financial_senses` namespace.
- files changed: none (inventory only)

## 2026-08-16 — Phase 1 (provider contract foundation)

- files: `scripts/lib/financial_senses/{__init__,result,provider,manifest,source_governance}.py`
- `FinancialSenseResult@v1`, `FinancialSenseProvider` protocol, `BaseProvider`,
  source classes + quality policy, registration manifest.
- tests: `test_provider_contract.py`

## 2026-08-16 — Phase 2 (SEC adapter)

- files: `sec_provider.py`, `sec_companyfacts_reader.py`, `sec_filing_diff.py`
- reuse: `db_adapter.get_connection()`, `sec_data_ingest._get_cik`; read-only
  EDGAR extension for company facts / metadata / diff.
- no duplicate scheduler, no production writes.
- tests: `test_sec_provider.py`, `test_sec_filing_diff.py`

## 2026-08-16 — Phase 3 (FRED/ALFRED macro + vintage)

- files: `macro_provider.py`, `macro_catalog.py`
- vintage-aware `value_as_of` / `compare_vintages`; `NOT_CONFIGURED` without key.
- tests: `test_fred_alfred_provider.py`

## 2026-08-16 — Phase 4 (instrument identity)

- files: `identity.py` — `InstrumentIdentity@v1`, fail-closed `resolve_identity`.
- tests: `test_instrument_identity.py`

## 2026-08-16 — Phase 5 (stress engine)

- files: `stress_engine.py` — three-tier deterministic stress + scenario library.
- tests: `test_stress_engine.py`

## 2026-08-16 — Phase 6 (factor/overlap)

- files: `factor_exposure.py` — sourced loadings + transparent overlap components.
- tests: `test_factor_exposure.py`

## 2026-08-16 — Phase 7 (claim/evidence graph)

- files: `evidence_graph.py` — graph model + provenance invariants + cycle detect.
- tests: `test_claim_evidence_graph.py`

## 2026-08-16 — Phase 8 (CIO critic shadow)

- files: `critic.py` — `CRITIC_SHADOW=1`, `CRITIC_BEHAVIOR_INFLUENCE=0`.
- tests: `test_cio_critic_shadow.py`

## 2026-08-16 — Phase 9 (OpenBB due diligence)

- files: `openbb.py` — `OPENBB_DECISION = DEFER`.

## 2026-08-16 — Phases 11–12 (testing + dry replay)

- tests: `test_security_source_governance.py`, `test_dry_replay.py`
- suite: **110 passed, 0 failed** (fully offline; live DB + network blocked).
- existing SEC regression: `tests/test_sec_form4_momentum_context.py` 17/17 pass.
- dry replay: 6 cases, 0 suggested actions, 0 production mutations, 0 Telegram
  sends. Vintage: `decision_time_value=5.5`, `latest_revised=5.9`,
  `revision_delta=0.4` (no backward leak). Critic shadow-only.

## 2026-08-16 — Phases 13–14 (integration contract + closeout)

- `INTEGRATION_WITH_AGENT_INTELLIGENCE_FOUNDATION.md` documents the registration
  contract; central gateway not touched.
- rebase/conflict audit: base is fresh `origin/main`; no rebase needed.

## Failures encountered and remediated

1. Missing `STATUS_INVALID_REQUEST` import in `provider.py` (NameError silently
   converted to `UNAVAILABLE`) → imported; added regression coverage.
2. SEC reader swallowed network errors as empty payloads (429/timeout looked
   like "no data") → reader now propagates errors; provider maps them to
   `UNAVAILABLE`.
3. Factor `_pearson` did not handle `None` returns in the replay fixtures →
   added `None` guards.

## Integration conflicts avoided

- Did not edit `docs/agent-intelligence/**`, `scripts/lib/agent_*.py`,
  `tests/test_agent_*.py`, central gateway, memory, ContextEnvelope,
  AgentRunTrace, deployment, systemd, cron, Telegram, or broker surfaces.

## Remaining dependencies

- Central MCP gateway registration — deferred to post-merge PR (AIF branch).
- Live FRED / OpenFIGI credentials — `NOT_CONFIGURED` until provided (contracts
  and fixtures are complete and honest).

## 2026-08-16 — Remediation pass (PR #340 financial-semantics hardening)

Adversarial review verdict: **HOLD — remediate on same branch, do not merge.**
Architecture accepted; closed the following financial-semantics and exact-head
defects. No redesign, no canonical SEC ingestion changes, no AIF overlap.

### P0-1 — FRED/ALFRED vintage semantics
- `compare_vintages()` now compares the **same observation date** across two
  vintages (decision-time value vs latest revised value for that observation),
  not "latest then" vs "latest now". Ordinary economic change is no longer
  mislabeled as a revision.
- `FredClient.vintage_dates()` parses the official JSON shape (list of date
  strings), not a list of objects.
- Renamed `macro.get_release_dates` → `macro.get_vintage_dates`.
- FRED request params URL-encoded via `urllib.parse.urlencode`.
- `decision_date` validated; malformed dates rejected.

### P0-2 — SEC XBRL like-for-like period semantics
- `latest_values()` and `_facts_at_period()` capture full XBRL context
  (`start`, `end`, `form`, `fp`, `fy`, `frame`, `filed`) and select the latest
  valid filing/amendment deterministically.
- `compare_filing_facts()` classifies duration kind (ANNUAL/QUARTERLY/YTD/
  INSTANT), requires matching units and fiscal period for duration facts, and
  returns `COMPARISON_UNAVAILABLE` (with reason) when equivalence cannot be
  established; `COMPARISON_NOT_APPLICABLE` for facts absent in both periods.
- `get_company_concept()` no longer lowercases taxonomy tags.

### P0-3 — OpenFIGI multi-identifier cross-validation
- Mapping-job boundaries preserved; per-identifier FIGI sets are intersected
  (1 → `RESOLVED`, >1 → `AMBIGUOUS`, 0 → `CONFLICT`).
- FIGI queries use `ID_BB_GLOBAL` (official v3 idType), not `ID_FIGI`.
- Supplied CUSIP/ISIN retained as asserted input evidence, not OpenFIGI output.
- Narrowing fields (`exchCode`, `securityType`) forwarded for `TICKER` jobs.

### P0-4 — FACT/CLAIM/MODEL_ESTIMATE boundary
- Added `ModelEstimate` and `Opinion` to `FinancialSenseResult` (`estimates[]`,
  `opinions[]`).
- `validate()` enforces `can_back_fact()`, requires `source_type`,
  `observed_at`/`as_of`, and `quality` on every `Fact`; `MODEL_INFERENCE`/
  `MEMORY_CONTEXT` cannot back a `FACT`.
- Stress `stress_estimated_pnl` is now a `ModelEstimate`, not a `Fact`.
- `BaseProvider.query()` validates its result before release and downgrades
  `OK` → `PARTIAL` with warnings on schema violations.

### P0-5 — stress shock unit contract
- `ShockValue {value, unit}` with `PERCENT` / `DECIMAL_RETURN` / `BASIS_POINTS`;
  normalized to decimal returns internally; ranges validated (`InvalidShock` →
  `INVALID_REQUEST`).
- Explicit canonical `portfolio_nav` required for `estimated_pct` when shorts
  or derivative exposures exist; `estimated_pct` is `unavailable` when NAV
  cannot be established. `cash_buffer_effect` is `None` until implemented.

### P1-1/P1-2 — critic generation identity + fail-closed evidence
- `critic_review_id` binds `decision_id`, `input_digest`, `evidence_digest`,
  and critic version.
- Missing `identity_status` defaults to `UNKNOWN` (not `RESOLVED`).
- Unmodeled portfolio effects above threshold contribute to
  `MATERIAL_OBJECTION`; absent evidence cannot yield `NO_MATERIAL_OBJECTION`.

### P1-3 — SEC status semantics
- No CIK → `NOT_FOUND`/`PARTIAL` (not `NOT_CONFIGURED`); DB failure reaches the
  structured `DATA_UNAVAILABLE` path (fixed `len(None)` ordering).

### P1-4 — claim graph authority
- Exposed evidence classes (`authoritative_fact_support`, `contextual_support`,
  `contradiction`) and claim statuses (`SUPPORTED`/`CONTEXTUAL_ONLY`/
  `CONTESTED`); `MEMORY_REF` is non-authoritative; stale facts preserved with
  freshness/invalidated metadata and are not actionable.

### P1-5 — exact-head CI + live smoke
- `.github/workflows/financial-senses-ci.yml` runs
  `python3 -m pytest tests/financial_senses/ -q` plus the existing SEC
  regression on PR changes to the financial-senses namespace (not
  branch-protection-required).
- `live_smoke.py` adds an optional, bounded, read-only live smoke harness
  (SEC unauthenticated; FRED/OpenFIGI only when keys are configured). Recorded
  separately from the unit-test PASS.

### Proof
- `tests/financial_senses/` suite: **162 passed, 0 failed** (fully offline).
- `tests/test_sec_form4_momentum_context.py`: **17/17 pass**.
- Provider-wide acceptance test (`test_acceptance_validate.py`): every
  supported capability returns `validate() == []`.
- production mutations: 0 · Telegram sends: 0 · DB writes: 0 ·
  authority: `READ_ONLY_ADVISORY`.

## 2026-08-17 — Second adversarial closeout (tight semantic defects)

Verdict: **HOLD — close narrow semantic defects; architecture still accepted.**
No redesign, no canonical SEC ingestion changes, no AIF overlap. These close
first-wave-vs-actual-semantics gaps that a green 162-test suite did not exercise.

### P0-1 — `BaseProvider` invalid-envelope fail-closed path
- `provider.py` now imports `STATUS_PARTIAL`; the fail-closed downgrade path can
  no longer raise `NameError` outside the fail-soft handler.
- New `test_invalid_ok_envelope_fails_closed_via_public_query` (and a
  missing-quality variant) exercise the **public** `query()` with a provider
  that returns `STATUS_OK` plus an invalid `Fact` (MODEL_INFERENCE source /
  missing quality) and prove: no exception escapes, status downgrades to
  `PARTIAL`, validation warnings are present, authority stays
  `READ_ONLY_ADVISORY`.

### P0-2 — evidence graph authority requires FACT
- `_evidence_classification()` now treats **only** a valid, fresh `FACT` as
  `authoritative_fact_support`. `SPECIALIST_OPINION`, `CLAIM`, `CASE_REF`,
  `SOURCE`, `DECISION`, and `MEMORY_REF` are each classified into their own
  non-authoritative buckets (`opinion_support`, `derived_claim_support`,
  `contextual_support`, `provenance_support`, `decision_support`).
- `claim_evidence()` `actionable` now requires ≥1 fresh authoritative FACT,
  no contradiction/invalidation, and a valid claim; `CONTESTED` can never be
  `actionable=true`. `INVALIDATES` edges are treated as blocking.

### P0-3 — SEC real QTD/YTD context pairing
- `duration_kind()` is now duration-first: actual `start`→`end` days classify
  ANNUAL/QUARTERLY/YTD before any `fp`/`frame` corroboration, so an `fp=Q2/Q3`
  six/nine-month YTD fact is no longer misread as quarterly.
- `_facts_at_period()` now returns a **list** of candidate contexts per tag
  instead of collapsing to one row; `compare_filing_facts()` pairs contexts
  like-for-like (annual↔annual, quarter↔quarter, YTD↔YTD, instant↔instant),
  collapses same-context amendments to the latest filing, and reports
  `ambiguous_context` / `no_like_for_like_pair` when no unique pairing exists.

### P0-4 — OpenFIGI warning/error jobs cannot disappear
- `cross_validate_identities()` gives every asserted identifier a first-class
  disposition; warning/error/no-result jobs surface as notes and yield
  `UNVERIFIED_IDENTIFIER` (never a clean `RESOLVED`) when others resolve.
  All-not-found yields `NOT_FOUND`.
- Provider exposes `job_dispositions` and surfaces warning/error text verbatim
  as warnings.

### P0-5 — stress completeness uses gross unmodeled exposure
- Added `modeled_gross_exposure`, `modeled_net_exposure`,
  `unmodeled_gross_exposure`, `unmodeled_net_exposure`; `unmodeled_value`
  remains as the documented signed-net alias.
- Provider `completeness` derives from `unmodeled_gross_exposure` (never signed
  net), so an unmodeled short or offsetting unmodeled long/short reports
  `PARTIAL`.

### P1-1 — ALFRED revision temporal provenance
- The revision-delta `Fact` now carries `as_of = retrieval_time` (when the
  latest vintage was read), not the historical `decision_date`; the
  decision-time value keeps `as_of = decision_date`. `retrieval_date` is exposed
  in the result data.

### P1-2 — test hygiene
- Removed the duplicate `test_model_inference_cannot_back_fact` (renamed one to
  `test_source_governance_assert_no_inference_as_fact`).
- Replaced the always-true `assert g.validate() == [] or True` with the real
  invariant `assert g.validate() == []`.
- `pytest --collect-only tests/financial_senses/` → 190 tests; within-file
  duplicate-name scan clean; always-true assertion scan clean.

### Proof (second closeout)
- `tests/financial_senses/` suite: **190 passed, 0 failed** (fully offline).
- `tests/test_sec_form4_momentum_context.py`: **17/17 pass**.
- CIO/research regression (representative): **81 passed**.
- `run_release_ci_equivalent.py --source-only`: **PASS (17/17)**.
- production mutations: 0 · Telegram sends: 0 · DB writes: 0 ·
  authority: `READ_ONLY_ADVISORY`.

## 2026-08-17 — Third closeout (final independent-review remediation)

Targets the 6 P1 merge blockers and the P2 critic/documentation defects from the
final independent review. Narrow semantic closeout, not a redesign.

### P1 — FRED/ALFRED real-time period semantics
- `FredClient.latest_as_of()` now bounds the real-time period on BOTH ends:
  `realtime_start = decision_date` **and** `realtime_end = decision_date`, plus
  `observation_end = decision_date`. A one-sided `realtime_end` is incorrect
  because FRED defaults both real-time bounds to today.
- Added REAL `FredClient` URL-capture tests (`test_latest_as_of_pins_realtime_period_both_ends`,
  `test_latest_as_of_no_realtime_period_by_default`,
  `test_observation_value_latest_vintage_unbounded_realtime`) that assert the
  actual HTTP query parameters, not the `FakeFredClient` abstraction.

### P1 — evidence-graph invalid-FACT authority bypass
- `_evidence_classification` now classifies FACT support via `_is_authoritative_fact`
  before bucketing; a non-stale but invalid FACT lands in a new
  `invalid_fact_support` bucket and can never enter `authoritative_fact_support`.
- Added adversarial tests: FACT missing source / `MODEL_INFERENCE` source /
  missing quality / missing `observed_at`/`as_of` are all non-authoritative and
  non-actionable; specialist opinion + invalid FACT remains non-actionable.

### P1 — OpenFIGI warning/error must prevent clean OK
- `cross_validate_identities` now treats any warning/error job (even with
  candidates) as non-clean; a single asserted identifier with warning/error is
  downgraded to `IDENTITY_UNVERIFIED`; the provider single-job path routes
  through `cross_validate_identities` too. Added `disposition` per job.
- Added single- and multi-job tests asserting BOTH `identity_status` and
  `FinancialSenseResult.status` (e.g. candidate+warning, candidate+error).

### P1 — factor/overlap missing data is not zero
- `holdings_overlap` / `sector_overlap` now return `UNAVAILABLE` when holdings
  or sector data is missing/empty — never a fabricated `0.0`.
- `FactorOverlapProvider` only emits a `holdings_jaccard` `Fact` when both inputs
  carry fact-capable `source`/`as_of`/`quality`; otherwise it emits a
  `ModelEstimate` (derived) and warns, so raw caller fixtures cannot be laundered
  into an `APPROVED_MARKET_DATA` world fact.

### P1 — SEC aggregate decision-evidence honest status
- `sec.get_decision_evidence` distinguishes `OK` / `NOT_INGESTED` /
  `NOT_APPLICABLE` / `DATA_UNAVAILABLE` per source and derives aggregate status
  (`OK` all read, `PARTIAL` partial, `UNAVAILABLE` all failed) + `quality.completeness`.
- `decision_evidence_subject` is emitted only with `source_ids` naming sources
  that were successfully consulted; the all-failed case emits no fabricated fact.

### P1 — broader cross-regression on exact-head CI
- `financial-senses-ci.yml` gains a second read-only `broader-regression` job
  running the exact deterministic representative set
  (`test_cio_decision_semantics`, `test_cio_decision_quality_pr1`,
  `test_research_governance_promotion_gate`, `test_research_empirical`) = 81 tests.

### P2 — shadow critic canonical actions + coverage semantics
- `_MATERIAL_ACTIONS` expanded to the canonical material vocabulary (ADD, EXIT,
  ROTATE, RAISE_CASH, RE_ENTER, DEPLOY_CASH, TRIM, ...) so they receive the same
  missing-evidence check.
- Fixed the coverage inversion: `coverage_pct` is modeled (unmodeled = 100 - v);
  `unmodeled_coverage_pct` is already unmodeled and is no longer subtracted.

### P2 — documentation truth
- `ACCEPTANCE.md` FS-24 → 222 tests; `FRED_ALFRED_PROVIDER.md`, `README.md`,
  `INTEGRATION_WITH_AGENT_INTELLIGENCE_FOUNDATION.md` renamed
  `macro.get_release_dates` → `macro.get_vintage_dates`; `MACRO_VINTAGE_POLICY.md`
  and ADR-003 now describe the two-ended real-time period; `TEST_AND_DRY_RUN_PLAN.md`
  → 222 tests.

### Proof (third closeout)
- `tests/financial_senses/` suite: **222 passed, 0 failed** (fully offline).
- `tests/test_sec_form4_momentum_context.py`: **17/17 pass**.
- Broader CIO/research representative regression: **81 passed**.
- `run_release_ci_equivalent.py --source-only`: **PASS (17/17)**.
- production mutations: 0 · Telegram sends: 0 · DB writes: 0 ·
  authority: `READ_ONLY_ADVISORY`.

## 2026-08-17 — Fourth closeout (true-final semantic closeout)

Targets the 3 P1 categories and 2 P2s from the independent exact-head review of
`e0445453`. One narrow semantic commit; no redesign, no CRLF normalization, no
merge/deploy, no AIF integration.

### P1 — evidence freshness requires explicit FRESH
- `_is_authoritative_fact()` now requires `freshness == "FRESH"` explicitly.
  `None` / `""` / `UNKNOWN` / an unrecognized value are NOT fresh and can never
  enter `authoritative_fact_support`; `STALE` remains `stale_fact_support`.
- Acceptance and dry-replay fixtures stamp `freshness: "FRESH"` explicitly.
- Added adversarial tests for `None`, `""`, `UNKNOWN`, an invalid enum, `FRESH`,
  and `STALE`.

### P1 — SEC YTD comparison is horizon-aware
- `_ytd_horizon()` discriminates YTD cumulative horizons: fiscal period when
  present (`Q2` vs `Q3`), else span bucketed with a 5-day tolerance. Q2-YTD vs
  Q3-YTD and 6M vs 9M are `COMPARISON_UNAVAILABLE`; same-fiscal-period YTD across
  years remains comparable; amendment selection and QTD/YTD fail-closed behavior
  are preserved.
- Added single-row and multi-context adversarial tests.

### P1 — factor loading/provenance governance
- `_coerce_loading()` now enforces the full contract (factor key, numeric
  loading, `method`, `window`, `as_of`, validated `quality`, governed `source`);
  missing metadata → `UNAVAILABLE`, never a partial loading.
- `_validated_upstream_provenance()` replaces the self-asserted provenance path:
  a `Fact` requires a structured `provenance` envelope (fact-capable
  `source_type`, immutable `source_ids`, `READ_ONLY_ADVISORY`, validated
  `quality` + `as_of`). Bare caller `source_type`/`as_of`/`quality` stays a
  `ModelEstimate`.
- Added provenance-forgery and incomplete-envelope adversarial tests.

### P2 — critic percentage bounds + provider security enumeration
- `coverage_pct` / `unmodeled_coverage_pct` are range-checked to `[0,100]`;
  missing/non-numeric/out-of-range → `DATA_UNAVAILABLE`, never a silent pass.
- `FactorOverlapProvider` added to `ALL_PROVIDERS` in the provider-wide
  read-only/security tests.
- CRLF normalization intentionally deferred to a separate mechanical cleanup.

### Proof (fourth closeout)
- `tests/financial_senses/` suite: **243 passed, 0 failed** (fully offline).
- `tests/test_sec_form4_momentum_context.py`: **17/17 pass**.
- Broader CIO/research representative regression: **81 passed**.
- `run_release_ci_equivalent.py --source-only`: **PASS (17/17)**.
- production mutations: 0 · Telegram sends: 0 · DB writes: 0 ·
  authority: `READ_ONLY_ADVISORY`.

## 2026-08-17 — Fifth closeout (merge-gate remediation)

Targets the 2 P1 defects and 1 P2 from the merge-acceptance review of
`159dd7aa`. One narrow semantic/manifest commit; no redesign, no CRLF
normalization, no merge/deploy, no AIF integration.

### P1 — governed quality enforced for FACT authority
- `FinancialSenseResult.validate()` and `ClaimEvidenceGraph.validate()` /
  `_is_authoritative_fact()` now require a `Fact`'s quality to be one of the
  governed `VALID_QUALITY` values (`HIGH`/`MEDIUM`/`LOW`/`UNKNOWN`). A non-empty
  but unrecognized quality (`BOGUS`, `NOT_VALID`, `HIGH_CONFIDENCE`) no longer
  validates as a governed Fact and can never enter `authoritative_fact_support`
  or make a claim actionable. Uses the existing `source_governance.VALID_QUALITY`
  constants — no new vocabulary.
- Added adversarial tests at both the envelope (`validate()`) and claim-graph
  authority layers.

### P1 — critic freshness semantics agree with FACT authority
- `review_decision()` now treats only explicit `FRESH` as current evidence.
  `STALE` is a freshness risk; `None`/`""`/`UNKNOWN`/unrecognized freshness is
  also flagged as not-current and does NOT count toward substantive-evidence
  content. A material action can no longer receive `NO_MATERIAL_OBJECTION`
  backed only by unclassified/non-fresh facts.
- Added adversarial tests for missing, `None`, `""`, `UNKNOWN`, invalid token,
  `FRESH`, and `STALE`, including a material-action case.

### P2 — registration manifest completeness
- `manifest.py` now registers `factor.overlap` and `critic.review` as
  `READ_ONLY` tools, matching the architecture's provider list.
- Added `tests/financial_senses/test_manifest.py` to prevent drift: every
  first-class provider and capability must appear in the manifest, and all
  manifest tools must be `READ_ONLY`.

### Proof (fifth closeout)
- `tests/financial_senses/` suite: **256 passed, 0 failed** (fully offline).
- `tests/test_sec_form4_momentum_context.py`: **17/17 pass**.
- Broader CIO/research representative regression: **81 passed**.
- `run_release_ci_equivalent.py --source-only`: **PASS (17/17)**.
- production mutations: 0 · Telegram sends: 0 · DB writes: 0 ·
  authority: `READ_ONLY_ADVISORY`.
