# Cross-Asset Decision Intelligence — Executable Backlog

Status: ACTIVE
Owner: Agent A (review/merge coordination); CADI implementation agent
as_of: 2026-10-09T11:17:14-04:00
Measured at: isolated local clone on base `3b5c248569908adfad9a60ca895e0fa9b2aa2c49`; temporary-store tests
Program readiness: **NOT READY**
Current ticket: **CADI-01 LOCAL IMPLEMENTATION; AUTHORITY APPROVAL PENDING**
Authority: current revision of the Implementation Plan; approved conversation plus Agent A's four binding additions

## Current executable backlog — 2026-10-09

The original `CADI-001`..`CADI-014` tickets below are retained historical records. They are not
aliases for the current `CADI-01`..`CADI-08` program. Historical DONE/self-review labels do not
complete current work. Only CADI-01 is authorized to start now; no downstream branch has started.

### CADI-01 — Canonical v2 contract, compatible history and visible row failures

- **Status:** LOCAL IMPLEMENTATION; blocked from completion/push by named new-store approval.
- **Purpose:** Remove incompatible canonical v1 ambiguity while preserving all prior evidence.
- **Files:** `scripts/lib/cross_asset/canonical_decision.py`, `decision_store.py`, assembly/export
  and legacy schema modules; `scripts/lib/cross_asset_decision.py` compatibility boundary;
  `scripts/cio_completeness_measurement.py`; `tests/test_cadi01_canonical_v2.py`;
  bounded read-only audit adapter in `scripts/lib/cio_operator_artifacts.py`;
  targeted tests; `config/data_source_authority.json`, `config/cio_surface_classification.json`;
  coordinator-owned GATES/derived authority docs/INDEX plus these existing five CADI documents.
- **Changes:** Version `SymbolDecisionObject@v2` with eleven groups, source/availability timestamps,
  account identity, history references and conservative authority; adapt both v1 shapes without
  rewriting historical rows. Append immutable/idempotent evaluations with concurrency protection;
  rebuild the latest projection from them through its declared single writer/read path.
- **Binding registration:** Register **each** new evaluation-history and projection store in DSA
  with its single writer in this PR (§7A), and classify every new output schema, including error
  receipts, in the classification registry. Actual operator approval provenance is required;
  missing approval blocks call-site activation and the authority gate, not just documentation.
- **Binding batch behavior:** Unknown action → a per-symbol error receipt with raw value, source
  and event reference; continue valid rows. No BUY/none substitution, dropped errors or batch abort.
- **Tests:** Both v1 shape adapters; preserved lineage/unknowns; v2 round-trip; repeat-event
  idempotency; concurrent append; restart/rebuild; corruption/write-failure visibility; one bad
  row among valid rows; all fifteen action classes; registered stores/schema classification;
  temporary stores only, no live mutation. See current Test Plan for acceptance expectations.
- **Risk:** Medium — contract migration and new authoritative stores, not trading authority.
- **Required reviewer:** Agent A plus independent architecture/QA reviewer coordinated by Agent A;
  no author self-review substitutes for independent acceptance.
- **Dependencies:** Existing v1 contracts, durable-root helpers, actual §7A source/writer approval.
- **Pass:** Local tests/authority gates establish preserved history, one writer and visible partial
  failures; normal reviewed PR. **Fail:** Loss/fabrication, unregistered/unapproved output or batch loss.
- **Rollback:** Disable v2 consumers and preserve immutable evidence; no deletion or legacy rewrite.
- **Execution record:** Base `3b5c248569908adfad9a60ca895e0fa9b2aa2c49`; local checkpoint recorded
  in Git/board after validation; remote PR/pushes NONE/0 of 2. Targeted **84 PASS**;
  intermediate broader **97 PASS / 8 authority FAIL**; release-equivalent **17/17 PASS**.
  Full acceptance exited 1 with authority and missing audit-read edges. The latter is repaired
  without starting CADI-07; its focused completeness test and combined 111-test run passed.
  Final proof: 121 combined PASS; 80 core PASS (overlap) after the final raw-symbol fix; 15
  adversarial PASS. Independent review cleared malformed-history/authority handling defects.
  Exact receipts are in the Test Plan. Both proposed approval blocks remain pending,
  not fabricated; production read also requires separate activation. No second writer.
  See current Test Plan for exact commands/artifacts. No activation, scheduler or production write.

### CADI-02 — Approved point-in-time source and identity/account linking

- **Status:** WAITING FOR CADI-01 MERGE; do not branch yet.
- **Purpose:** Assemble one sourced intelligence record rather than duplicate private desk stores.
- **Files:** Existing `cross_asset/assemble.py`, research-spine reader/adapter boundaries and approved
  data-broker projections; temporary-store fixtures. Final file claims go on the board before work.
- **Changes:** Link security/subject/issuer identity, research, CIO, signals and account-local position
  evidence with observed/available timestamps. Unknown cash/quantity/identity stays unknown. Reuse
  the CIO-owned research spine and approved positions reader; never a second positions writer.
- **Tests:** Conflicting/unresolved identity, stale/missing sources, out-of-order availability,
  account split under 100 shares, positions direction/sign and provenance reconciliation.
- **Risk:** Medium. **Reviewer:** Agent A plus governance/data reviewer.
- **Dependencies:** Merged CADI-01, approved existing sources and v2 adapter contract.
- **Pass/Fail/Rollback:** Correct provenance/account coverage; fail on invented joins/quantities;
  disable new adapters and preserve evidence.

### CADI-03 — Priced expression comparison and full blocker accounting

- **Status:** WAITING FOR CADI-01 MERGE; no downstream branch now.
- **Purpose:** Compare expressions economically, not by static family order.
- **Files:** Existing `cross_asset/expression_router.py` and approved options payoff/projection
  adapters; economics fixtures. Broker execution/lifecycle code is outside this ticket.
- **Changes:** Shares, CSP, long call, covered call, protective put, collar and debit/credit spreads
  on common horizon/capital assumptions; executable quotes, costs, financing/dividends/assignment
  caveats; separate economic/liquidity/portfolio/procedural blockers and distance to passing.
  Missing input → unknown/scenario-only, never an invented fill or approved trade.
- **Tests:** Independently calculated single/multileg payoff cases, executable-price sides,
  missing costs/quotes, account cover, simultaneous blockers and stable evidence labels.
- **Risk:** High. **Reviewer:** Agent A plus independent options-risk/economics reviewer.
- **Dependencies:** Merged CADI-01; CADI-02 source interfaces as needed; approved stored snapshots.
- **Pass/Fail/Rollback:** Checked economics with honest exclusions; fail on fake executable prices;
  disable comparison, retaining scenarios and evidence.

### CADI-04 — Frozen forecast model and independent validation

- **Status:** WAITING FOR CADI-01 MERGE; no downstream branch now.
- **Purpose:** Establish whether physically forecasted return evidence supports incremental EV.
- **Owner:** **Parfit** (sole model author). **Independent model-risk reviewer:** **Halley**, who
  must not author this implementation. Agent A reviews integration; **John alone promotes**.
- **Files:** New forecast module/artifact contract within the cross-asset boundary, approved daily
  price reader and chronological validation fixtures; new output classification/GATES serialized.
- **Changes:** Reproducible volatility-conditioned historical-return bootstrap; up to five years
  of prior data, minimum 504 clean sessions, horizons up to 63 sessions. Chronological splits,
  purging, horizon embargo, date-clustered uncertainty and unconditional/zero-drift baselines.
- **Freeze point:** Before held-out validation freeze preprocessing, cutoff, config, seeds and
  code SHA. Version/hash the artifact and report; changes require a new version and untouched
  validation. Freeze per release; no runtime retraining, automatic promotion or silent replacement.
- **Tests:** Reproducibility/leakage guards, calibration/distribution metrics, minimum 100 matured
  held-out forecasts over 20 distinct dates per supported horizon, independent comparison.
- **Risk:** High. **Dependencies:** Merged CADI-01, approved retained prices and complete economics.
- **Pass/Fail/Rollback:** Halley validates and John approves exact artifact hash/scope; fail on
  leakage or unvalidated model. Retain scenario-only `NO_PROVEN_WINNER` when any gate fails.

### Named prerequisite — CADI_OPTIONS_ARCHIVE_RETENTION / PGVECTOR_DISK_FLOOR

- **Status:** PENDING; not measured by this documentation sidecar; **CADI-06 blocked before start**.
- **Producer:** CADI implementation agent measures live stores **read-only** and supplies the
  numbers in a PR'd packet. Agent A reviews and presents options to John; John records the named
  decisions. This is not an assignment for John to calculate capacity.
- **Files:** A dedicated measurement document proposed in its reviewed PR, current CADI doc
  references and authorized follow-on policy changes only. No additional file is created here.
- **Required measurements:** Pinned root/SHA/as_of, observation/sample counts, current retention,
  bytes per snapshot and variation, capture frequency, symbol/contract counts, actual compression,
  heap/TOAST/index overhead, available disk/headroom, daily/window growth and peak migration
  space (coexistence, rebuild and temporary files). Show formulas and measured-versus-estimated
  labels. Missing archive coverage is NOT MEASURED, never zero-sized evidence.
- **Pgvector:** Measure the actual reserved-space figure, configured floor and shared-filesystem
  allocation; include its reserve in capacity options. `PGVECTOR_DISK_FLOOR` remains a separate
  pending operator decision; do not lower the current floor, activate pgvector or migrate it.
- **Risk:** High for retention/authority changes. **Reviewer:** Agent A; decision owner John.
- **Acceptance:** Reproducible, reviewed measurement packet and named approved retention/budget/
  headroom decision before CADI-06. Proposed 365-day retention is not approval.
- **Rollback:** No policy change pending decisions; retain existing pruning/floor behavior.

### CADI-05 — Event reevaluation plus governed n8n reconciliation

- **Status:** WAITING FOR REQUIRED STAGE 2 CONTRACTS; not started.
- **Purpose:** Every eligible source event yields a decision or visible error receipt.
- **Files:** Existing cross-asset events/hooks and runner boundary; **same PR** edits
  `config/lane_registry.json` and `config/n8n_run_allowlist.json`; associated tests/output schema
  classification. Agent A owns workflow generation.
- **Changes:** Durable queue, idempotent event keys, coalesced prices, retries and actual research
  queue linkage. Five-minute worker **only as an n8n lane under AGENTS.md §23/§9.3**: fixed argv,
  dedicated `safe_flock` lock, genuine non-mutating `--dry-run`, output_signal and durable receipt.
- **Binding row timing:** `kind="n8n"` registry row and allowlist entry land together; expression
  is a placeholder until Agent A generates the workflow and John imports it under a grant. State
  temporary ORPHANED until its first scheduler-shadow receipt in the PR body. Never invent the id.
- **Tests:** Event coverage, restart/retry/dedup/locking, refusal boundary, forbidden-writer checks,
  neutral-cwd pinned runner dry-run and scheduler-versus-decision receipt isolation.
- **Risk:** Medium. **Reviewer:** Agent A plus operations/security reviewer.
- **Dependencies:** Required CADI-02/03/04 contracts, classified outputs, approved source boundaries,
  governed import/activation. No timer, cron, backdoor trigger or allowlist bypass.
- **Pass/Fail/Rollback:** Host receipts and outputs establish scheduler-shadow → canary → live;
  fail on silent omission/duplicate schedule. Stop consumer under grant, preserve queue/history.
- **Mode distinction:** `scheduler-shadow` means n8n dry-run; `decision-shadow` means organic
  advisory decision persistence. Record both; scheduler-shadow never counts toward organic days.

### CADI-06 — Real replay, approved archives and missed-opportunity evidence

- **Status:** BLOCKED BEFORE START pending CADI_OPTIONS_ARCHIVE_RETENTION and Stage 2 dependencies.
- **Purpose:** Replace the zero-signal placeholder with honest point-in-time 30/60/90-day evaluation.
- **Files:** Existing `run_cross_asset_historical_replay.py` and cross-asset ledger/archive reader
  boundaries; approved archive writer/pruner policy after John decision; replay fixtures.
- **Changes:** Walk real signals, reconstruct only then-available evidence, compare actual recorded
  expression with contemporaneous engine result; retain quote/event/universe versions under the
  approved budget. Missing proposal, correctly blocked alternative and proven economic miss are
  different ledger classes. Never guess that a signal became a shares transaction.
- **Tests:** Anti-lookahead, historical version selection, unavailable contracts, out-of-order
  events, incomplete/pending maturity, repeat-run determinism and explicit cohort denominators.
- **Risk:** High. **Reviewer:** Agent A plus independent data/QA reviewer.
- **Dependencies:** Merged CADI-01, Stage 2 contracts, named retention decision and measured capacity;
  pgvector remains optional/unactivated and its existing floor preserved.
- **Pass/Fail/Rollback:** Non-placeholder real cohorts with quantified coverage/exclusions; fail on
  current quotes or synthetic premiums called history. Preserve records and keep NOT READY.

### CADI-07 — Cached read-only API, lineage and mobile UI

- **Status:** WAITING FOR STABLE STAGE 3 OUTPUTS; not started.
- **Purpose:** Explain comparison, evidence quality and root causes without page-load computation.
- **Files:** Existing CIO intelligence API/projection and Command Center component boundaries,
  exact disjoint file claims determined by Agent A before work; API/desktop/mobile tests.
- **Changes:** Cached projections with refresh timestamp, lineage, coverage, model version,
  decision-shadow labels, queue age/priority/job linkage and clickable blockers. No fitting,
  replay or research initiated by page paint; no invented top twenty or financial-action control.
- **Tests:** Source/API/UI reconciliation, stale/partial states, refresh bounds and phone access.
- **Risk:** Medium. **Reviewer:** Agent A plus independent frontend QA.
- **Dependencies:** Stable CADI-05/06 projections and surface/model approvals.
- **Pass/Fail/Rollback:** Traceable cached read-only UI; fail on untraceable/triggered computation;
  disable feature without losing evidence.

### CADI-08 — QA, evidence, readiness and delivery

- **Status:** Continuous validation obligation; current sidecar test runs **NOT RUN**.
- **Purpose:** Prove before/after state and prevent source/CI/delivery being mislabeled readiness.
- **Files:** These five existing documents plus coordinator-approved evidence artifacts/test gates;
  independent reviewers own checks, authors do not declare their own work complete.
- **Changes:** Record exact SHA, commands/results/counts, artifact hashes, source roots/timestamps,
  classification/authority findings, residual risk and rollback; separate local/merged/live/organic.
- **Tests:** Dedicated unit/integration/persistence/CIO/research/options/reentry/watchlist/replay/
  regression tests; full acceptance and exact-SHA CI; fourteen consecutive organic decision-shadow
  days with at least 99% eligible-event receipt coverage. Keep synthetic and scheduler evidence apart.
- **Risk:** High if readiness overclaimed. **Reviewer:** Agent A and independent QA/model-risk as
  applicable; John owns final promotion/release decision.
- **Dependencies:** Each ticket's delivered proof; real historical coverage and model promotion.
- **Pass/Fail/Rollback:** All gates and no untested high/critical defects; otherwise NOT READY and
  NO_PROVEN_WINNER. Verify Drive content parity/email receipts separately; no delivery claim here.

### Handback and process checklist

1. CADI-01 lands alone. Then CADI-02/03/04 may branch in parallel; then CADI-05/06; then CADI-07.
2. Announce serialized-file PRs on `~/N8N_PROGRAM_BOARD.md` before opening; append
   `time, CADI agent, ticket, PR, head SHA` for every PR. Agent A owns board and merge train.
3. Two-push budget, full local acceptance before push, normal hook, exact-SHA authorization;
   no self-merge/deploy, and no unquoted cron strings (`*` expands to filenames).
4. This sidecar writes **only these existing five docs**; no INDEX/GATES/registry/board edit,
   staging, commit, push, merge, deployment or new branch. Coordinator handles generated files.
5. Before state is named base; after code/runtime state remains NOT MEASURED. Preserve September
   test records as history; do not reuse their counts as current passes.

---

## Historical backlog — 2026-09-29 (preserved, not current sequencing)

as_of: 2026-09-29  
Authority: `docs/CROSS_ASSET_DECISION_INTELLIGENCE_IMPLEMENTATION_PLAN.md`

## Tickets

### CADI-001
- **Title:** SymbolDecisionObject@v1 schema + validator
- **Purpose:** Canonical object with required field groups; refuse unknown authority.
- **Files:** `scripts/lib/cross_asset/__init__.py`, `scripts/lib/cross_asset/symbol_decision_object.py`
- **Changes:** dataclass/dict schema, `validate_symbol_decision()`, `new_symbol_decision()`
- **Tests:** `tests/test_cross_asset_symbol_decision_object_20260929.py`
- **Risk:** Low
- **Required reviewer:** Staff Eng (self) + CIO Ops on merge

### CADI-002
- **Title:** Append-only persistence ledger
- **Purpose:** Persist decisions to `data/cio/symbol_decisions.jsonl` without mutating callers on failure.
- **Files:** `scripts/lib/cross_asset/persistence.py`
- **Changes:** `append_symbol_decision()`, `load_latest_by_symbol()`
- **Tests:** same unit file (tmpdir)
- **Risk:** Low
- **Required reviewer:** Staff Eng

### CADI-003
- **Title:** Assemble from existing stores (best-effort)
- **Purpose:** Build object from symbol + optional Hermes result id / holdings / provenance dicts (no live DB required in unit tests).
- **Files:** `scripts/lib/cross_asset/assemble.py`
- **Changes:** `assemble_symbol_decision(symbol, *, provenance=, hermes_result=, holdings_row=, signal=, cio=)`
- **Tests:** fixture-based assemble for NFLX-like payload
- **Risk:** Medium (partial data honesty)
- **Required reviewer:** Staff Eng

### CADI-004
- **Title:** Expression router (shadow)
- **Purpose:** For Buy/Hold/Reentry/Sell, emit ExpressionCandidate list using strategy matrix; mark absent families unavailable.
- **Files:** `scripts/lib/cross_asset/expression_router.py`
- **Changes:** `route_expressions(signal_kind, position_state, options_hints=)`
- **Tests:** matrix coverage + collar unavailable
- **Risk:** Medium
- **Required reviewer:** Options desk owner + Staff Eng

### CADI-005
- **Title:** Shadow cycle CLI
- **Purpose:** One-shot evaluate symbols from a list; write ledger; never trade.
- **Files:** `scripts/ops/run_cross_asset_shadow_cycle.py`
- **Changes:** CLI `--symbols NFLX,AAPL --dry-run/--apply-ledger`
- **Tests:** dry-run path in unit test via import
- **Risk:** Low
- **Required reviewer:** Ops

### CADI-006
- **Title:** Missed-opportunity expression ledger
- **Purpose:** Record when chosen expression ≠ top-ranked shadow expression.
- **Files:** `scripts/lib/cross_asset/missed_opportunity_ledger.py`
- **Changes:** append to `data/cio/expression_missed_opportunities.jsonl`
- **Tests:** counterfactual fixture
- **Risk:** Low
- **Required reviewer:** Staff Eng

### CADI-007
- **Title:** Historical replay harness (30/60/90 scaffolding)
- **Purpose:** Replay signal JSONL windows; compute metrics stubs when price/chain archives absent (honest INSUFFICIENT_DATA).
- **Files:** `scripts/ops/run_cross_asset_historical_replay.py`
- **Changes:** window args; metrics JSON out
- **Tests:** empty archive → INSUFFICIENT_DATA metric path
- **Risk:** Medium
- **Required reviewer:** QA Lead

### CADI-008
- **Title:** Register hermetic gates
- **Purpose:** Add tests to `run_cio_hardening_ci.py` GATES.
- **Files:** `scripts/run_cio_hardening_ci.py`
- **Changes:** gate `cross_asset_decision_intel_20260929`
- **Tests:** gate registration presence test optional
- **Risk:** Low
- **Required reviewer:** Staff Eng

### CADI-009
- **Title:** Event hook stub (flag-gated)
- **Purpose:** `maybe_reevaluate_on_research_complete(symbol, result_id)` no-op unless `CROSS_ASSET_SHADOW=1`.
- **Files:** `scripts/lib/cross_asset/events.py`
- **Changes:** flag check + assemble+route+persist
- **Tests:** flag off → no write
- **Risk:** Medium
- **Required reviewer:** Staff Eng

### CADI-010
- **Title:** Docs — test plan + readiness (living)
- **Purpose:** Auditable trail through shadow and recommendation.
- **Files:** `docs/CROSS_ASSET_DECISION_INTELLIGENCE_TEST_PLAN.md`, `docs/CROSS_ASSET_DECISION_INTELLIGENCE_READINESS_REPORT.md`
- **Changes:** update after each phase
- **Tests:** n/a (doc)
- **Risk:** Low
- **Required reviewer:** CIO Ops Architect

### CADI-011 — DONE (hermetic)
- **Title:** Hermes complete → shared spine upsert
- **Purpose:** Organic producer: when Hermes stamps a completed result, append
  `SecurityResearchSpine` (gated by `CROSS_ASSET_SPINE` / `CROSS_ASSET_SHADOW`).
- **Files:** `scripts/lib/cross_asset/hooks.py`, `scripts/lib/cio_hermes_research.py`
- **Changes:** `notify_hermes_result_completed` fail-soft after `_persist_stamped_result`
- **Tests:** `tests/test_cadi_spine_hooks_20260929.py`
- **Honesty:** hermetic ≠ OBSERVED until promote + live Hermes complete with flag on

### CADI-012 — DONE (hermetic)
- **Title:** Desk consumers prefer shared spine
- **Purpose:** Options / watch / reentry / holdings see the same CIO thesis.
- **Files:** `hooks.overlay_thesis_fields_from_spine`, `symbol_thesis_attach.thesis_fields_for_symbol`,
  `options_engine._research_universe_rows` / `_reentry_research_rows`
- **Changes:** overlay on thesis attach; spine rows first in options universe merge; reentry overlay
- **Tests:** `tests/test_cadi_spine_hooks_20260929.py` (+ spine unit file)
- **Honesty:** wiring proven hermetically; organic E2E needs Bill C live canary

### CADI-013
- **Title:** Spine coverage metric
- **Purpose:** % of researched symbols with POPULATED spine
- **Status:** open

### CADI-014
- **Title:** CC API spine read
- **Purpose:** `GET /api/v2/research/spine/{symbol}`
- **Status:** open

---

## Order of execution

1. CADI-001 → 002 → 003 → 004 → 005 → 008 (ship Phase 1–3 core)  
2. CADI-006 → 007 → 009  
3. CADI-010 continuous updates  
4. CADI-011 → 012 (producer/consumer hooks) — **landed hermetic 2026-09-29**  
5. CADI-013 → 014; UI deferred until shadow metrics exist  
6. Organic OBSERVED canary after promote + `CROSS_ASSET_SPINE=1`  
