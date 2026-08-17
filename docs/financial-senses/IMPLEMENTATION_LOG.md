# Implementation log

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
