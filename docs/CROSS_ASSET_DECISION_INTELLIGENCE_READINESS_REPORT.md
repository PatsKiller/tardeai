# Cross-Asset Decision Intelligence — Readiness Report

Status: ACTIVE  
Owner: Agent A (readiness review); CADI agent (evidence collection); John (operator decisions)
as_of: 2026-10-09T11:17:14-04:00
Measured at: isolated CADI-01 clone on base `3b5c248569908adfad9a60ca895e0fa9b2aa2c49`; fixture tests, no served-runtime changes
Current ticket: **CADI-01 LOCAL IMPLEMENTATION; AUTHORITY APPROVAL PENDING**
Architecture Complete: **NO**
Go-Live Recommendation: **NOT READY**
Default comparison outcome: **NO_PROVEN_WINNER**

## Current readiness — 2026-10-09

**Local foundation implemented, not complete or live.** Canonical v2, both lossless adapters,
immutable/idempotent history, rebuildable projection, row-level failure isolation, registry
proposals, classifications and a registered test gate are now implemented in an isolated clone.
All five documents reflect the approved revision and Agent A's additions. Source approval is
pending, so authority/full acceptance is not green. No PR/push, merge, deployment, scheduler,
model promotion, production store write or downstream branch has been performed.

### Before / after record

| Item | Before at named base | After local CADI-01 implementation |
|---|---|---|
| Schema | Two incompatible code paths advertise SymbolDecisionObject@v1 | v2 + both lossless read adapters; compatibility and malformed-input tests pass |
| Economics | Router expected_value null, structural order | Priced/model-validated comparison specified; no new winner or model proof |
| Replay | Archive-present harness explicitly returns signals_evaluated=0 and not-implemented note | Real point-in-time replay required; no new replay run or nonzero metric claimed |
| Scheduling | Old documents proposed a timer | Current plan prohibits timer/cron; future CADI-05 must be a reviewed n8n lane; nothing activated |
| Authoritative stores | No unified v2 history/projection writer | Both proposed rows have one writer; approvals deliberately pending; four new schemas classified |
| Unknown action | Malformed legacy actions could become none | Durable raw-action/source/event receipts; valid remainder survives; six falsy values explicitly tested |
| Persistence | Audit attachment capped at 50; competing v1 formats | Full legacy evidence retained; immutable SQL triggers, concurrency/idempotency and rollback/rebuild tests pass |
| History | September execution/test/replay claims | Preserved verbatim below, explicitly historical; not relabeled current acceptance |

### Current test and historical validation status

| Evidence category | Current result | Scope |
|---|---|---|
| Targeted/regression tests | **121 combined PASS; 80 core PASS (overlap); 15 adversarial PASS** | Six-suite run 551.41s; latest core 16.03s; adversarial 12.54s; each exit 0. Fixture evidence, not production readiness |
| Regression / release-equivalent | Full acceptance **exit 1**; release-equivalent **17/17 PASS** | Eight authority failures plus missing audit-read completeness; the read gap repaired and focused completeness + combined 111 tests passed; final rerun required |
| DSA / schema classification / payload-flow guards | **AUTHORITY BLOCKED** | Two pending approvals, one writer each; all four schemas classified; bounded existing audit surface now covers decisions/errors/latest views without copying |
| Historical 30/60/90-day replay | **NOT RUN** | Last retained September table: 0/0/0 evaluated, null superiority; not fresh measurement |
| Organic decision-shadow | **NOT MEASURED** | No fourteen-day evidence window established here |
| Scheduler-shadow / n8n canary/live | **NOT RUN** | Future CADI-05 lane; cannot substitute for organic decisions |
| Forecast validation / artifact promotion | **NOT RUN / NOT APPROVED here** | Parfit owner, Halley independent reviewer; frozen artifact needs John's named decision |
| Live release / Drive parity / email package | **NOT VERIFIED in this sidecar** | Old delivery receipts do not prove current completion |

### Defined blockers, owners and required resolution

| Finding | State / owner | Evidence required before closure |
|---|---|---|
| CADI-01 canonical migration | LOCAL IMPLEMENTATION / CADI agent; Agent A review pending | Local proof exists; complete only after approved sources, final acceptance and reviewed PR/merge |
| New store and schema authority | PENDING / CADI-01 agent; John source approval | Each new store registered with single writer in same PR; actual approval provenance; every new output classified; gates run |
| CADI-02/03/04 start | WAITING / Agent A | CADI-01 merged alone before any of these branches |
| CADI_OPTIONS_ARCHIVE_RETENTION | PENDING / CADI agent measures; Agent A presents; John decides | PR'd read-only live measurements of snapshot bytes/frequency/symbols/contracts/compression/index/peak space; approved retention/budget/floor before CADI-06 starts |
| PGVECTOR_DISK_FLOOR | PENDING / CADI agent measures reserve; John decides | Actual configured floor/reserved-space/shared-disk figure and reviewed capacity implications; existing floor not lowered |
| Forecast artifact | NOT BUILT/VALIDATED by this sidecar / Parfit + Halley | Frozen-before-held-out configuration, reproducibility, chronological validation, independent review and operator promotion of exact hash/scope |
| CADI-05 scheduler | NOT STARTED / CADI agent + Agent A | Same-PR kind=n8n row/allowlist; fixed argv, real --dry-run, dedicated safe_flock, output receipt; placeholder expression; granted import; scheduler-shadow → canary → live |
| Temporary ORPHANED window | EXPECTED FUTURE LIMITATION / Agent A | Disclose in CADI-05 PR until first scheduler-shadow receipt; do not hide other health failures or invent workflow ids |
| Real economics/replay/UI | NOT COMPLETE / CADI-03/06/07 owners | Comparable priced evidence; then-available history; quantified exclusions; cached read-only API and desktop/mobile reconciliation |
| Organic decision evidence | NOT OBSERVED here / CADI-05/08 + QA | Fourteen consecutive organic decision-shadow days, >=99% eligible-event receipt coverage, error/coverage denominators |

The temporary workflow placeholder is a documented accepted window, not a completed integration.
Other entries are explicit pending engineering/operator/evidence dependencies, not undefined
findings or permissions to mark them accepted. Proposed 365-day retention is not policy; no
capacity figure is invented, and no pgvector migration is implied.

### Exit criteria and recommendation

Retain **NOT READY** until all are established on the actual candidate:

1. CADI-01 independently reviewed/merged before downstream branches; histories preserved,
   per-row failures visible, stores approved/registered and output schemas classified.
2. Targeted/regression/full local acceptance and exact-SHA CI pass with command/result artifacts;
   no untested critical/high defects. Missing environment or authority gates remain failures/blocks.
3. Complete priced alternatives with conservative `NO_PROVEN_WINNER` unless validated probabilities,
   risk constraints and positive incremental net-EV confidence bound clear that default.
4. Real 30/60/90 cohorts with required historical evidence, denominators, exclusions and paired
   outcomes. Nonzero signal counts alone do not establish superiority or sufficient coverage.
5. Frozen release model with Parfit ownership, Halley independent review and John's recorded exact
   artifact promotion; no automatic retraining/promotion or risk-neutral POP called predictive alpha.
6. Fourteen consecutive **decision-shadow** days and >=99% eligible-event receipt coverage, excluding
   fixtures, manual fires and **scheduler-shadow**. n8n rows are not host/economic evidence.
7. Agent A/John release review, exact-SHA grants as needed, served source/process/API/UI pin and
   tested rollback. Documented Drive parity/email receipts are a separate delivery requirement.

Code landing in about a week and readiness about three weeks out are estimates only. Missing
history, model validation, capacity decisions or outcome maturity may extend them. Shipping a
working advisory shadow system does not change this report to READY without the full proof.

---

## Historical readiness report — 2026-09-29 (preserved, not current test results)

Status: ACTIVE
as_of: 2026-09-29T17:55:00-04:00  
Measured at: worktree `wt/cross-asset-decision-intel` after Phase 1–3 scaffold + hermetic green  
Authority: Operator program 2026-09-29  
See also: Implementation Plan, Test Plan, Backlog

---

## Architecture Complete

**NO** (scaffold only through Phase 3 expression router; Phases 4–10 incomplete)

Completed:
- SymbolDecisionObject@v1 schema + validator + JSONL persistence
- Assemble from Hermes/provenance/holdings/signal/CIO/options packet snapshots
- Shadow expression router for Buy/Hold/Reentry/Sell with honest `collar` unavailable
- Flag-gated research-complete hook (`CROSS_ASSET_SHADOW`)
- Missed-opportunity expression ledger
- Historical replay CLI that refuses invented counterfactuals (`INSUFFICIENT_DATA`)
- Shadow cycle CLI (dry-run / apply-ledger)

Not complete:
- Live event wiring into Hermes/watch/reentry producers (stub only)
- Chain-priced EV / comparable ranking engine
- UI
- Continuous shadow systemd
- 30/60/90d archive-backed replay with metrics that answer “would options have been superior?”

---

## Tests Passed

**8 / 8** hermetic (`tests/test_cross_asset_symbol_decision_object_20260929.py`)

Evidence: `/tmp/cadi_pytest.txt` — `8 passed in 0.27s`  
Gate registered: `cross_asset_decision_intel_20260929` in `run_cio_hardening_ci.py`

## Failed Tests

**0** (current suite)

---

## Historical Validation Results

| Window | data_quality | signals_evaluated | options_superior_rate |
|---|---|---|---|
| 30d | INSUFFICIENT_DATA | 0 | null |
| 60d | INSUFFICIENT_DATA | 0 | null |
| 90d | INSUFFICIENT_DATA | 0 | null |

Artifact: `/tmp/cadi_hist_metrics.json` (regenerate via `scripts/ops/run_cross_asset_historical_replay.py`)

**Honesty:** Without signal/price/chain archives, the harness correctly refuses to invent superiority metrics.

---

## Known Risks

1. Expression `expected_value` is null — ranking is structural order, not EV.  
2. Collar remains unavailable (matrix ABSENT).  
3. Shadow flag default OFF — no continuous reevaluation in production yet.  
4. Assembled objects from live stores not yet wired; fixtures prove shape only.  
5. Promoting this module without EV model would create false confidence in “top_family”.

---

## Technical Debt

- Duplicate decision payload families still coexist (DecisionPayload@v1, OptionsDecisionPacket@v2, SymbolDecisionObject@v1) — intentional adapter stage.  
- No Postgres projection for SymbolDecisionObject.  
- No CC UI.  
- Historical archives not defined/contracted.

---

## Go-Live Recommendation

### **NOT READY**

**Reasoning:** The program asked whether the system can answer “highest expected-value expression of that thesis, and can we prove it?” Today we can:
- enumerate candidate expressions honestly,
- persist a canonical object,
- run shadow dry-runs,
- refuse fake historical superiority claims.

We **cannot** yet prove EV superiority across shares vs options with chain economics, continuous shadow evidence, or 30/60/90d counterfactuals. Production routing on this scaffold would over-claim.

### Conditional path to READY
1. Wire Phase 4 events + run shadow ≥14 days with ledger growth metrics.  
2. Implement Phase 6 EV using real chains; keep advisory.  
3. Land archives + Phase 9 metrics with non-null superiority rates on a defined universe.  
4. Operator review of Readiness READY + feature flag grant.

---

## Auditable trail (this cut)

| Artifact | Path |
|---|---|
| Plan | `docs/CROSS_ASSET_DECISION_INTELLIGENCE_IMPLEMENTATION_PLAN.md` |
| Backlog | `docs/CROSS_ASSET_DECISION_INTELLIGENCE_BACKLOG.md` |
| Test plan | `docs/CROSS_ASSET_DECISION_INTELLIGENCE_TEST_PLAN.md` |
| Code | `scripts/lib/cross_asset/*`, `scripts/ops/run_cross_asset_*.py` |
| Tests | `tests/test_cross_asset_symbol_decision_object_20260929.py` |
| Commits | `bc9b38c1d` + `1a406daa5` on `wt/cross-asset-decision-intel` |
