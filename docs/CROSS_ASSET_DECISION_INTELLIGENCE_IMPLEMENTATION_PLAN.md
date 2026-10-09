# Cross-Asset Decision Intelligence — Master Implementation Plan

Status: ACTIVE  
Owner: Agent A (program supervisor); CADI implementation agent (ticket delivery)
as_of: 2026-10-09T14:46:01-04:00
Measured at: isolated CADI-01 source `3c1c294fa22a68609e4e54b3f32fb40ed57da1d0`, integrated main `cb851ce8ef66aa5d1a45dbe96fd0a9ef805a78cf`; fixture/regression evidence, not live behavior
Program readiness: **NOT READY**
Current ticket: **CADI-01 LOCAL ACCEPTANCE PASS; EXACT-SHA PUSH APPROVAL / AGENT A PR REVIEW PENDING**
Current tests: **80 canonical PASS; full native acceptance exit 0; 348 parallel units + 20 serial gates PASS; adversarial 15 PASS**; earlier overlapping targeted run **155 PASS**
Authority: approved revised CADI plan and Agent A's four binding additions, recorded in the operator conversation
Canonical repo path: `docs/CROSS_ASSET_DECISION_INTELLIGENCE_IMPLEMENTATION_PLAN.md`

### Latest checkpoint — integrated main and one-pass acceptance

Status: LOCAL ACCEPTANCE COMPLETE; remote/release steps pending. Date: 2026-10-09.
Commit tested: `3c1c294fa22a68609e4e54b3f32fb40ed57da1d0`. Agent A's explicit ruling permits
INDEX generation in this isolated feature branch without taking another session's shared lease.
Main `cb851ce8ef66aa5d1a45dbe96fd0a9ef805a78cf` was merged normally; all newer gates,
classifications and ratified AGENTS.md 3.0.0 policy were preserved. The index was regenerated
after staging and checked. No peer worktree, lease or production state was edited.

Exactly **one** `bash scripts/ai_local_acceptance.sh` ran with `CIO_CI_JOBS=2`, the shared
interpreter and the isolated `m2_shadow_test_231db057820d` database. Result: **exit 0**,
`ready_to_request_sync: true`, all four local green flags true. Release-equivalent **17/17**;
all **348 parallel units and 20 serial gates**; canonical v2 **80/80**; adversarial **15/15**;
authority **zero findings**, one writer for each CADI store; dark-contract NEW **0**;
host-path NEW **0**; source-of-truth `stale: none`. No timing-file or full-suite rerun occurred.
The native unit lines report **11,510 passed test executions, 62 skipped executions and two
expected failures**. These are execution counts, not unique tests; optional/skipped paths are
not live proof. Detailed before/after evidence is in the Test Plan.

Complete transcript: `~/cadi-evidence/cadi01-main-acceptance-20261009-Fk5shS/acceptance.log`,
SHA256 `32e25c491d5dde3f158c9081e99784ba77179bc18ff6be4fdc8a875a1c7c30bb`.
This run's generated adversarial HTML/unit exports were moved into that same evidence packet,
preserved rather than deleted. Runtime/test source hashes are unchanged from the reviewed
approval checkpoint. Independent integration review found no blocking issues: all **336**
existing gates and **141** classification entries retained; one gate and four classifications
added. Read-only governed verifier receipt: `3566869b-137d-4078-9d4f-4e0ce3b97183`.

Before: named approvals were fixed, but the final integration/index/acceptance were pending.
After: integrated candidate is locally accepted; a documentation-only checkpoint and index
regeneration record it. Exact-SHA native push approval is requested only after that checkpoint.
Agent A owns PR review and merge; this agent does not merge, deploy or activate CADI. The
supervisor's main advanced during this one-pass run, so the PR must disclose its tested base;
no second, untested tree is silently called accepted. Full program stays NOT READY,
NO_PROVEN_WINNER, with no downstream branch before CADI-01 merge.

### Named registration checkpoint — 11:53 EDT (historical before-state)

John replied "approved" to the explicit request naming `cross_asset_evaluation_history`,
`cross_asset_decision_projection`, their sole writer `scripts/lib/cross_asset/decision_store.py`
and **no production activation**. Both registry rows now reference
[`CADI01_SOURCE_APPROVAL_ARCHIVE_MANIFEST_20261009.md`](governance/CADI01_SOURCE_APPROVAL_ARCHIVE_MANIFEST_20261009.md#cadi01-source-approval-20261009).
This supersedes the pending-approval states in the earlier local checkpoint retained below;
it does not relabel that failed acceptance run as green. The approval checkpoint is committed as
`d8431c7eb4a3f3b724e5d8deefe146470bd97e59`. Seven targeted suites passed **155 tests / 0 failures /
exit 0 / 409.67s**, including the native authority clean-gate assertion and negative controls.
Independent approval review found no blocking issues; Ruff/format, source-of-truth, dark-contract,
coverage and SOP checks passed. Full acceptance on the integrated final candidate is **NOT RUN**.
Latest fetched main is `ac3fddebb`; merging it and final docs-index regeneration are deferred
because peer `root/runtime-convergence` holds `docs/INDEX.md` lease
`29ceb237-16da-42b6-ad59-6e0fc5bea4cf` (still active at 11:53 EDT).
Agent A must arrange a release/handoff; the request is on the shared board. After handoff:
integrate main, regenerate after explicit staging, rerun full local acceptance with bounded
concurrency, commit the final candidate, and request its exact-SHA git-push grant.
Production read activation, production store writes, scheduling and all downstream tickets
remain off/not started. Agent A owns review, merge and release. Program remains NOT READY.
Peer leases on the backlog/readiness report and docs index are respected; their earlier status
text is historical until its owner incorporates this checkpoint.

## Current governing revision — 2026-10-09

This revision controls future work. The complete September document below is preserved as
historical evidence, including its original execution claims. Its v1-only design, timer proposal,
delete-module rollback, self-review and weaker readiness criteria are **not** current instructions.
Approval of this engineering plan is not an operator data-source grant, retention decision, model
promotion, workflow activation, merge or deployment authorization. The original source base
advertised AGENTS.md 3.0.0 as PROPOSED; integrated main now records its operator ratification and
ACTIVE status. Apply the current ratified text and the safer rule; ratification alone does not
activate a runtime capability or grant financial authority.

### Before state and delivery boundaries

| Evidence at the named base | Before state | What this update proves |
|---|---|---|
| `scripts/lib/cross_asset/symbol_decision_object.py` and `scripts/lib/cross_asset_decision.py` | Both advertise `SymbolDecisionObject@v1`; incompatible canonical shapes coexist | Canonical v2 and lossless adapters added; legacy payloads preserved |
| `scripts/lib/cross_asset/expression_router.py` | Structural routing; candidate `expected_value` is null | No priced or model-validated superiority demonstrated |
| `scripts/ops/run_cross_asset_historical_replay.py` | Archive-present branch explicitly returns zero evaluated signals and says replay is not implemented | No fresh replay performed; no invented replay metrics |
| Retained readiness/test documents | 30/60/90-day table is 0/0/0; eight-test pass belongs to September | Historical evidence, not acceptance of CADI-01 |
| Current local ticket | No unified v2 history/projection writer | Canonical v2 fixture writer, named approvals, 80 canonical tests and full acceptance now pass; PR/merge/deployment/activation remain distinct gates |

The separate decision object must consume existing CIO-owned research, identity and positions
readers; it must not create private thesis stores or a second positions writer. Missing identity,
cash, shares, research or quotes stays unknown rather than zero. Covered-call cover remains local
to each account. Source being deployed, a Drive copy existing, or a sent status email is not proof
of a working end-to-end engine.

### Target architecture and interfaces

```text
SymbolDecisionObject@v2
  identity              # canonical security/subject/issuer IDs, account context, provenance
  equity_thesis         # current thesis, confidence, invalidation and version references
  research_state        # results, gaps, queue linkage, priority, age
  event_state           # catalysts, earnings, regime; observed_at and available_at
  signal_state          # explicit action, raw source value, source/event identity
  position_state        # account-local quantities, cash/coverage evidence; unknown is unknown
  options_state         # retained quote/contract refs, IV, liquidity, restrictions
  cio_state             # decisions, changes, reasons and confidence references
  historical_state      # previous evaluations, ownership/outcomes and thesis history refs
  expression_comparison # candidates, blockers, evidence class, NO_PROVEN_WINNER by default
  audit_history         # durable lineage references, model version and source versions
```

- Preserve adapters for **both** existing v1 shapes; do not rewrite or delete old ledgers. Preserve
  input lineage and archived versions instead of silently discarding fields.
- New evaluation history and rebuildable projections are new authoritative stores under §7A.
  **Register each in `config/data_source_authority.json`, naming its single writer, in CADI-01's
  PR.** Record actual operator approval provenance; never invent it or treat Agent A review as a
  grant. If approval is missing, report the authority gate as blocked and do not activate a writer.
- Every new output schema, including projection and error receipts, must be classified in
  `config/cio_surface_classification.json` in the same PR. No competing writer or private read path.
- Use durable persistent-state resolution, immutable/idempotent evaluations, concurrent-write
  protection, and projections rebuildable from the ledger. Keep full history outside bounded views.
- Explicitly support BUY, STRONG_BUY, ADD, ADD_ON_PULLBACK, REENTRY, ENTRY_NEAR, UPGRADE,
  CONVICTION, HOLD, MONITOR, HEDGE, SELL, TRIM, REDUCE and EXIT. Normalize documented aliases only.
- An unknown action produces a **visible per-symbol error receipt** containing its raw value,
  source and event reference; process the rest of the batch. Do not substitute BUY/none, silently
  drop the row, or let one bad row abort valid evaluations. Expose partial-batch failure honestly.
- All evaluations remain `READ_ONLY_ADVISORY`, with no financial action and no memory behavior
  authority. Scheduler modes and decision evaluation modes are separate receipt dimensions.

### Serialized sequence, ownership and milestones

| Stage | Tickets | Dependencies and ownership |
|---|---|---|
| 1 | CADI-01 schema, v1 adapters, registered stores and classifications | **Land alone first**; Agent A reviews and controls the merge |
| 2 | CADI-02 source linking; CADI-03 economics; CADI-04 forecast | Only branch after CADI-01 is merged; parallel disjoint ownership from that merged contract |
| 3 | CADI-05 reevaluation and n8n lane; CADI-06 replay/archive/ledger | Required Stage 2 contracts first; CADI-06 additionally waits for the named retention decision |
| 4 | CADI-07 cached API and mobile UI | Stable evaluation/replay projections from Stage 3 |
| Continuous | CADI-08 independent QA and evidence | Runs through every stage; does not imply downstream implementation may start early |

Parfit is the sole CADI-04 model owner; Halley is the independent model-risk reviewer and does not
author that model. Agent A owns the board, independent PR review, merge train, release requests
and promote verification. John owns operator decisions and model promotion. Other ticket owners
declare disjoint file/store sets through Agent A before implementation.

Announce serialized-file PRs on `~/N8N_PROGRAM_BOARD.md` before opening them. For each PR append
`time, CADI agent, ticket, PR, head SHA`. Shared schema, authority/classification, registry, GATES
and INDEX edits are coordinated, not concurrently overwritten. Use one worktree/branch/PR per
ticket, budget two pushes, normal hooks, and no self-merge. This sidecar owns only the five existing
CADI documents: it does not edit the board, INDEX, GATES, registries or source code. The coordinator
owns final regeneration and integration after documentation handback.

### Economics, forecast and ranking — CADI-03/04

Compare appropriate shares, CSP, long call, covered call, protective put, collar and debit/credit
spread expressions at a common horizon and capital basis. Reuse existing payoff mathematics;
include executable bid/ask, known fees/slippage, financing, dividends and assignment limitations.
Separate trade risk, liquidity, portfolio and procedural blockers and their distance to passing.
Structural availability and illustrative scenarios are not predictive EV or a proven winner.

The proposed forecast is a reproducible volatility-conditioned historical-return bootstrap using
approved existing daily prices/dependencies, at most five years of prior observations, at least
504 clean sessions, and supported horizons up to 63 trading sessions. Use chronological
train/calibration/test splits, purge overlapping labels, embargo by horizon, and date-clustered
uncertainty. Compare against unconditional historical and existing zero-drift baselines. Require
at least 100 matured held-out forecasts across 20 distinct forecast dates per supported horizon.

Before held-out validation, freeze preprocessing, configuration, cutoff, seeds and code SHA.
Version/hash the resulting model and validation artifacts; any adjustment creates a new version
requiring untouched validation. Artifacts are **frozen per release**; no runtime retraining,
silent replacement or automatic promotion. Only a recorded **John operator decision** may promote
an exact artifact hash and its supported scope, after Halley's independent review.

`NO_PROVEN_WINNER` stays the default. A model-supported winner needs validated probabilities,
complete economics, satisfied risk constraints, and a positive confidence bound on incremental
net EV versus shares. Missing data or failed validation retains scenario-only/non-authoritative
output. Do not turn risk-neutral POP into demonstrated forecasting alpha.

### Reevaluation, n8n and the two shadows — CADI-05

Wire research, thesis, equity signal, positions, price, IV, earnings, liquidity and CIO changes to
a durable deduplicated queue. Coalesce repeated price updates, retry transient failures, and link
research gaps to actual queue jobs rather than claiming research exists from a label.

The five-minute reconciliation worker is an **n8n lane under AGENTS.md §23/§9.3**. No new cron
line, timer, competing scheduler or temporary timer is permitted. Its single PR adds:

1. A `config/lane_registry.json` row with `scheduler.kind="n8n"` and `output_signal`.
2. A matching `config/n8n_run_allowlist.json` entry with fixed argv, a real non-mutating `--dry-run`,
   its own `safe_flock` lock and durable receipt contract.
3. Tests for forbidden-writer boundaries, deduplication, lock behavior, refusal and mode isolation.

**The row and allowlist entry land together.** Its scheduler expression remains a placeholder
until Agent A generates the workflow and the operator imports it under a named grant. A temporary
`ORPHANED` state until the first scheduler-shadow receipt is expected and must be stated in the PR
body; it is not an excuse to fabricate a workflow id or receipt or suppress unrelated failures.
If the allowlist rejects an authoritative writer, stop for an approved boundary design; do not
weaken the never-list or route around the gateway.

Use only relay → coordination gateway → executor. Agent A generates the exported workflow;
operator import/activation follows its grant. Progress **scheduler-shadow → canary → live** with
host `RunReceipt@v1`, lock and output evidence at each step. Cron text is always quoted; a bare `*`
must never be passed through shell word splitting or pathname expansion.

| Term | Meaning | What it does not prove |
|---|---|---|
| scheduler-shadow | n8n `dry_run` lane fires and host execution receipts | Organic advisory decision production or fourteen-day evidence |
| decision-shadow | Real source signals yield persisted advisory comparisons without financial action | Workflow activation, broker authority or trading permission |

Record both dimensions explicitly in receipts, docs and monitor projections. Synthetic fixtures,
manual fires and scheduler-shadow cannot be counted as organic decision-shadow days.

### Named storage decisions and replay — CADI-06

**CADI-06 must not start until `CADI_OPTIONS_ARCHIVE_RETENTION` is recorded by John.** Extending
options retention to 365 days is a proposal, not approved policy. The CADI implementation agent
produces a **PR'd measurement packet** from read-only live-store inspection; Agent A reviews it
and presents the alternatives to John. The agent supplies the numbers, not a request that John
calculate them. Existing writers/pruners and retention remain unchanged pending the decision.

The packet must contain pinned root/SHA and measurement time, sample bounds/counts, current
retention, bytes per snapshot (including variability), observed capture frequency, symbols and
contracts per snapshot, actual compression, table/TOAST/index overhead, filesystem headroom,
projected daily and proposed-window growth, and **peak migration space** including coexistence
and rebuild/temp overhead. Distinguish measured values from forecasts and show calculation and
assumptions; absence of a contract archive is an explicit measurement gap, never zero bytes.

`PGVECTOR_DISK_FLOOR` is a separate **pending named operator decision**. The same packet measures
pgvector's reserved-space figure from the actual stores/configuration and shared filesystem;
no invented reserve or lowering of the existing floor. Account for that reserve in archive
capacity. CADI uses existing readers and does not implicitly activate pgvector or migrate it.
Current packet measurements and both approvals: **PENDING / NOT MEASURED by this sidecar**.

Once authorized, implement real point-in-time 30/60/90-calendar-day replay and align retention
writers/pruners to the approved budget. Report discovered signals, reconstructed decisions,
priced comparisons, exclusions, pending/matured outcomes and coverage denominators. Distinguish
predicted EV, illustrative scenarios and observed outcomes. Do not fill missing historical chains
with current quotes, synthetic premiums, revised earnings dates or later research. Missing
proposal, correctly blocked expression and proven missed economic opportunity are separate ledger
classes; record the actual decision rather than assuming shares were chosen.

### API/UI and readiness — CADI-07/08

Use cached read-only CIO projections with model/version, source lineage, evidence class, refresh
time, coverage, blockers and root-cause drill-through. A page paint must not start research, fitting
or replay. Test desktop/mobile. Do not invent twenty eligible opportunities to fill a ranking.

| Phase | Pass | Fail | Rollback | Owner | Dependencies |
|---|---|---|---|---|---|
| 1 Canonical | Both v1 adapters, immutable/idempotent persistence, classified registered outputs, visible row errors | Lost history, unapproved writer or one bad row aborts batch | Disable v2 consumers; preserve ledger | CADI-01 agent + Agent A | §7A approval; existing contracts |
| 2 Linking | Point-in-time source/account identity reconciles; unknown stays unknown | Fabricated GUID/quantity or cross-account cover | Disable new adapters | CADI-02 agent + governance review | Merged CADI-01 |
| 3 Routing | Required families and independently checked priced payoff fixtures | Fake executable prices or hidden constraints | Disable comparison | CADI-03 agent + options-risk reviewer | CADI-01/02; approved snapshots |
| 4 Reevaluation | Every eligible event yields decision/error receipt; retry/dedup tests pass | Silent omission, duplicate scheduling or broker action | Stop consumer; retain queue | CADI-05 agent + Agent A | CADI-02/03/04; n8n approvals |
| 5 Missed ledger | Expected versus actual proposal linkage with evidence classes | Missing proposal called profitable without evidence | Disable projection; retain evidence | CADI-06 agent + QA | Approved retention; actual decisions |
| 6 Ranking | Frozen validated artifact, common economics and default NO_PROVEN_WINNER | Lookahead, heuristic EV or unapproved model promotion | Scenario-only output | Parfit + independent Halley | CADI-03/04; John promotion |
| 7 UI | Cached API reconciliation, timestamps and mobile/read-only drill-through | Triggered fitting/research or untraceable recommendation | Disable UI/API feature | CADI-07 agent + QA | Stable Stage 3 outputs |
| 8 Decision-shadow | Fourteen consecutive organic days; at least 99% eligible-event receipt coverage | Scheduler-shadow/fixtures counted as organic | Stop lane under grant; retain records | CADI-05 agent + Agent A/QA | Reviewed n8n lane; no execution authority |
| 9 Validation | Real signals processed in all windows, quantified exclusions and paired outcomes | Zero-signal placeholder called success or fake fills | Keep NOT READY | CADI-06/08 + independent QA | Approved archive scope; matured evidence |
| 10 Recommendation | Exact-SHA acceptance/CI, independent review, organic/replay/model proof and operator release decision | Any unmet evidence gate or untested critical/high defect | Governed prior-release rollback | Agent A + John | All gates and grants |

### Current execution entry and evidence discipline

#### Local committed checkpoint — 2026-10-09

Status: **LOCAL CODE COMMITTED; CADI-01 NOT COMPLETE / NOT PUSH-READY**.
Implementation commit: `aace8c83437656e72131a01ce08712ff39a82b3c` on
`wt/cadi01-canonical-decision-20261009`, base `3b5c248569908adfad9a60ca895e0fa9b2aa2c49`.
Files changed: 20 files in the implementation commit; new canonical/store/test files, legacy
adapters and exports, bounded operator audit reader, schema discovery, two registries, GATES,
five CADI documents and generated AGENTS/source-of-truth/INDEX. `git show --stat` is the exact
manifest; source hashes and JUnit receipts are in the Test Plan.

| Component | Local status | Proof / boundary |
|---|---|---|
| Canonical v2 + both v1 adapters | COMPLETE locally | Action/identity/authority/JSON tests; original payload and audit history preserved |
| Immutable history + latest projection | COMPLETE locally on fixtures | Idempotency, concurrency, rollback, corruption/rebuild/reopen; no production store activation |
| Existing audit-read integration | COMPLETE locally | Three record edges, bounded read, corruption preserves legacy results; default production read disabled |
| Documentation and registered validation | COMPLETE locally | Five docs, GATES, schemas, single-writer proposals; 121 combined + 80 core overlapping + 15 adversarial PASS |
| Named source approvals | BLOCKED / John | Two pending approval records; authority exit 1; no substitute/fabricated provenance |
| Full final acceptance / reviewed PR | NOT COMPLETE | Rerun after approval, request exact-SHA push grant; normal hooks, Agent A review/merge |

Pushes used: **0/2**. PR: **NONE**. Merge/deployment/scheduler/broker/trade: **NOT DONE**.
Every later CADI ticket remains unbranched until Agent A merges CADI-01. This is not a production
recommendation and does not replace NOT READY with a code-completion claim.

Status: **LOCAL IMPLEMENTATION; NOT COMPLETE / NOT PUSH-READY**
Date: 2026-10-09
Source base: `3b5c248569908adfad9a60ca895e0fa9b2aa2c49`
Local branch: `wt/cadi01-canonical-decision-20261009`
Commit: local checkpoint recorded by the Git history and board after validation; no remote commit/PR yet.
Files changed: new `canonical_decision.py`, `decision_store.py`, `test_cadi01_canonical_v2.py`;
legacy adapter/assembly/export modules; completeness schema discovery; GATES; both registries;
generated AGENTS/source-of-truth/INDEX and all five existing CADI documents.
Final scoped tests: **121 PASS** across six suites; the last raw-symbol serialization safeguard
and two additional cases were retested in the **80-PASS core** run (overlapping, not additive).
Fresh adversarial suite: **15 PASS**. Exact commands/artifacts/hashes are in the Test Plan.
Intermediate broader run: **97 PASS / 8 FAIL**; all eight fail on pending new-store approvals.
Release-equivalent source checks: **17/17 PASS**. Full local acceptance exited **1**: eight
source-approval test failures and a completeness failure for three unconnected audit schemas.
The audit-read gap was repaired through the existing operator-artifacts surface and its focused
completeness test passed; the combined post-fix selection passed **111 tests** before two more
negative controls were added. Final scoped rerun is recorded below at checkpoint.
Subsequent read-only review found malformed JSON-shape failure paths; shared error/projection
validation and protected envelope construction repaired them. Eight corruption cases passed;
the reviewer cleared both findings. Legacy artifact listings remain usable when CADI is corrupt.
Authority is explicitly not green. No approval record, skip or baseline adjustment was invented.
Independent scoped review: known defects cleared; malformed actions/GUIDs, authority laundering,
identity conflicts, exact timestamp ordering and raw action preservation retested.
Downstream branches/tickets: **NOT STARTED; wait for Agent A's CADI-01 merge**.

The new store proposals are `cross_asset_evaluation_history` and
`cross_asset_decision_projection`, written only by `scripts/lib/cross_asset/decision_store.py`
into separate tables of `cio/cross_asset_decisions.sqlite`. No production writer or scheduler
was added. A bounded read-only audit adapter uses the existing operator-artifacts endpoint;
production reads require both approved registry rows and `TRADEAI_CADI_RECORDS_READ_ENABLED=1`.
Neither approval nor activation is set here. The reader never copies data into the artifact
store, invents persistence time or creates a second writer. Fixture tests use temporary paths.
`approved_by`/`approved_on` remain
null until John's actual named source/writer approval; the authority gate correctly refuses them.
Four new schemas are classified. SQLite transactions make the history/projection write atomic,
and triggers reject history update/delete/replacement. Legacy ledgers remain unchanged;
unknown rows create durable error receipts without dropping good rows. `NO_PROVEN_WINNER` remains
mandatory; these are structural/advisory evaluations, not priced forecasts or demonstrated alpha.

Rollback: leave new callers disabled, preserve history, keep v1 readers. Nothing was scheduled,
merged, deployed, imported into n8n or connected to a broker. Full results and fixture artifacts
are recorded in the Test Plan; runtime validation, retention measurements, replay and fourteen
organic decision-shadow days remain later gated work.

After each real milestone append exact commit, files, commands, counts, hashes, before/after state
and residual risk. Agent A, not the author alone, marks validated completion. Preserve the old
evidence and distinguish source-present, locally tested, merged, deployed and naturally observed.
Drive parity and email attachment/delivery receipts are separate delivery gates. `NOT READY`
persists while historical coverage, model promotion or organic evidence is missing. A week of
coding/three weeks to readiness is an estimate, never a readiness promise or permission to skip
fourteen organic decision-shadow days. This local foundation changes no production flags or state.

---

## Historical document — 2026-09-29 (preserved, not current instructions)

Status: ACTIVE
as_of: 2026-09-29T17:45:00-04:00  
Measured at: repo `wt/cross-asset-decision-intel` @ base `86e228273` + this program’s commits  
Canonical repo path: `docs/CROSS_ASSET_DECISION_INTELLIGENCE_IMPLEMENTATION_PLAN.md`  
Authority: Operator directive 2026-09-29 — Plan → Build → Test → Validate → Shadow → Readiness  
Supersedes: none (new program)  
See also: `docs/CROSS_ASSET_DECISION_INTELLIGENCE_TEST_PLAN.md`, `docs/CROSS_ASSET_DECISION_INTELLIGENCE_PRODUCTION_BILL.md`, `docs/CROSS_ASSET_DECISION_INTELLIGENCE_BACKLOG.md`, `docs/CROSS_ASSET_DECISION_INTELLIGENCE_READINESS_REPORT.md`, `scripts/lib/options_decision_packet_v2.py`, `scripts/lib/agent_decision_payload.py`, `scripts/lib/options_strategy_matrix.py`, `scripts/missed_opportunity_policy.py`

---

## 0. Program north-star

> For every investment decision in the platform, what is the highest expected-value **expression** of that thesis (shares / long call / CSP / spread / covered call / protective put / collar), and can we **prove** it with lineage?

**Hard rule:** advisory-only until Readiness says READY. Shadow mode records decisions; it does not place orders.

---

## 1. Current State (measured)

### 1.1 What exists today

| Surface | What is real |
|---|---|
| **Portfolio** | Holdings JSON + broker sync; CIO product surfaces book; positions drive coverage gates for covered calls. |
| **Watchlists** | `watch_directives` + ranked `/api/v2/watchlist`; directive promote bounded; Hermes research queue; provenance per symbol. |
| **CIO** | Desk loop, situations, operator product, reentry book (Surface A), gap resolver + pending fulfill. |
| **Hermes** | Research requests/results JSONL + projection; specialist artifacts; lineage envelopes. |
| **Options Desk** | `OptionsDecisionPacket@v1/v2`, strategy matrix (CC/CSP/PP/long call/debit/credit), enterprise desk, research universe, identity GUIDs. |
| **Re-Entry** | Reentry decision desk statuses (READY/NEAR); CIO situations read desk read-only. |
| **Research** | Hermes + llm_curation interim; operator watch research priority; thesis fields often `INSUFFICIENT_DATA`. |
| **Signal Generation** | Screeners, watch alerts, proposal lifecycle, active trader policies — **per-lane**, not unified. |
| **Scheduler** | systemd + cron on CURRENT; Hermes workers; CIO telegram loop. |
| **Persistence** | Postgres (directives, watchlist) + `data/cio/*.jsonl` ledgers + persistent-state symlink. |
| **Decision lineage** | `DecisionPayload@v1` (flagged `AGENT_DECISION_PAYLOAD`), agent run traces. |
| **Missed opportunity** | `missed_opportunity_policy.py` — proposal timing classification only (not expression EV). |

### 1.2 What partially exists

- Options vs stock **comparison** inside OptionsDecisionPacket (stock_play / options_play) — not generalized to every Buy/Hold/Sell/Reentry signal.
- Identity linking (`subject_guid`, `issuer_guid`, options identity) — used in options/CIO lineage, **not** as a single SymbolDecisionObject.
- Shadow / measurement flags (`AGENT_DECISION_PAYLOAD`, memory shadow) — not a cross-asset expression shadow.
- Collar family listed in `ABSENT` matrix set — known gap.

### 1.3 What is missing

- Canonical **SymbolDecisionObject** spanning equity thesis → expression ranking.
- Unified update path triggered by research complete / signal / position change / CIO situation.
- Cross-asset **ranking engine** with comparable EV / R:R / risk units across expressions.
- Missed-opportunity **ledger** for “shares chosen when CSP/call was superior” (and reverse).
- Historical replay harness for 30/60/90d expression counterfactuals.
- UI surface for SymbolDecisionObject.
- Production go-live gate for expression routing (today: NOT READY).

### 1.4 What is duplicated

- Decision-shaped payloads: DecisionPayload@v1, OptionsDecisionPacket@v2, proposal packets, alert routing decisions, risk decisions.
- Symbol identity resolution in multiple libs (identity_registry, options_identity, desk evidence gatherers).

### 1.5 What is disconnected

- Hermes completed research does not always open/fulfill operator pending (fixed partially 2026-09-29 for interim+queue; broader expression reevaluation still unwired).
- Options desk packets do not systematically refresh when watchlist research lands.
- Reentry READY does not auto-evaluate CSP vs shares vs spread.
- Aegis / defense surfaces are separate from options expression ranking.
- Scheduler fires lane jobs; no single “reevaluate SymbolDecisionObject” consumer.

---

## 2. Gap Analysis (capability matrix)

| Capability | Status | Complexity | Risk | Dependencies |
|---|---|---|---|---|
| SymbolDecisionObject schema | Missing → **building Phase 1** | Medium | Low | identity_registry, JSONL append hygiene |
| Assemble from portfolio/watch/CIO/Hermes/options | Missing → Phase 1–2 | Large | Medium | holdings, provenance API, hermes results, options packets |
| Cross-system identity linking | Partial | Medium | Medium | subject_guid / issuer_guid consistency |
| Options expression router (Buy/Hold/Reentry/Sell) | Partial (matrix only) | Large | High | options chains, quotes, cash, share coverage |
| Event-driven reevaluation | Missing | Large | Medium | research complete events, watch alerts, position deltas |
| Missed opportunity ledger (expression) | Partial (timing only) | Medium | Low | SymbolDecisionObject history |
| Cross-asset ranking engine | Missing | Large | High | comparable EV model, risk unit, liquidity |
| UI integration | Missing | Medium | Low | CC v3 API + SymbolDecisionObject store |
| Shadow mode continuous | Missing → Phase 3/6 | Medium | Low | scheduler, no broker writes |
| Historical 30/60/90 replay | Missing | Large | Medium | historical prices, past signals, options chains archive |
| Production go-live | Missing | Large | High | readiness report READY + operator approval |

---

## 3. Target Architecture

### 3.1 SymbolDecisionObject (canonical)

```
SymbolDecisionObject@v1
  identity              # symbol, subject_guid, issuer_guid, as_of
  equity_thesis         # stance, summary, conviction, invalidation, source refs
  research_state        # hermes_request_id, result_id, status, age_hours
  event_state           # catalysts, regime, material flags
  signal_state          # buy|hold|sell|reentry|none, lane, signal_id, fired_at
  position_state        # held qty, accounts, cost basis band, coverage
  options_state         # packets[], chain_as_of, liquidity notes
  cio_state             # situation ids, product refs, advisory stance
  historical_state      # prior decisions[], outcomes refs
  expression_comparison # ranked ExpressionCandidate[]
  audit_history         # who/what/when updates
```

**ExpressionCandidate:** `{ family, structure, expected_value, reward_to_risk, max_loss, pop, blocks[], rank, shadow_only }`

Families evaluated by signal class (shadow):

| Signal | Expressions |
|---|---|
| Buy | shares, long_call, CSP, call_spread (debit) |
| Hold | shares, covered_call, protective_put, collar* |
| Re-entry | shares, CSP, spread |
| Sell | sell_shares, collar*, protective_put |

\*collar remains `ABSENT` in matrix → candidate may be `status=unavailable` until implemented.

### 3.2 Ownership

| Field group | Owner writer | Readers |
|---|---|---|
| identity | `cross_asset.assemble` via identity_registry | all |
| equity_thesis / research_state | Hermes projection + assemble | CIO, options router |
| signal_state | lane emitters (watch/reentry/alerts) | router |
| position_state | holdings snapshot | options gates |
| options_state | options desk builders | ranking |
| expression_comparison | `cross_asset.expression_router` | UI, ledger, shadow |
| persistence | `cross_asset.persistence` → `data/cio/symbol_decisions.jsonl` | API, replay |

### 3.3 Update paths / event triggers

1. Hermes research COMPLETED for symbol → assemble + route (shadow).  
2. Watch alert / CIO BUY-ish signal → assemble + route.  
3. Reentry status → READY/NEAR → assemble + route.  
4. Position delta (shares cross 100 / cash change) → refresh Hold expressions.  
5. Nightly batch → historical + missed-opportunity ledger.  

### 3.4 Persistence

- Append-only JSONL: `data/cio/symbol_decisions.jsonl` (schema `SymbolDecisionObject@v1`).  
- Optional projection index later; Phase 1 is file-ledger only (matches CIO pattern).  
- Authority: `READ_ONLY_ADVISORY` on every row.

---

## 4. Implementation Milestones

### Phase 1 — Canonical SymbolDecisionObject
Schema, validate, persist, assemble stub, unit tests.

### Phase 2 — Cross-system identity linking
Wire subject_guid/issuer_guid; join Hermes result + watch provenance + holdings.

### Phase 3 — Options routing layer (shadow)
Expression router for Buy/Hold/Reentry/Sell using strategy matrix + honesty (blocks / unavailable).

### Phase 4 — Event-driven reevaluation
Hooks from Hermes complete + reentry desk + watch alert emitters (flag-gated).

### Phase 5 — Missed opportunity ledger
Expression counterfactual ledger distinct from proposal timing policy.

### Phase 6 — Cross-asset ranking engine
Comparable EV scoring + rank stability tests.

### Phase 7 — UI integration
CC read API + thin Symbol Intelligence panel (no trade buttons).

### Phase 8 — Shadow mode
Continuous cycle CLI + systemd timer candidate; record only.

### Phase 9 — Production validation
Historical 30/60/90 harness + metrics; failure budget.

### Phase 10 — Go-live
Operator approval; feature flag; rollback pin.

---

## 5. Acceptance Criteria (per phase)

| Phase | Pass | Fail | Rollback | Owner | Dependencies |
|---|---|---|---|---|---|
| 1 | Schema validate + persist roundtrip tests green; sample assemble for NFLX | Invalid schema written to ledger | Delete feature module; no flag on | Staff Eng | identity helpers |
| 2 | Linked IDs present when stores have them; hermetic fixtures | Fabricated GUIDs | Disable linker | Staff Eng | Phase 1 |
| 3 | Each signal class emits ranked candidates; collar unavailable honest | Silent skip of required family | Flag off | Options + Staff | matrix |
| 4 | Event hook fires assemble in dry_run | Hook writes broker | Flag off | Staff Eng | Phase 2–3 |
| 5 | Ledger rows for sample counterfactuals | Overwrites timing policy | Separate file only | Staff Eng | Phase 3 |
| 6 | Rank metrics on fixture set | Unbounded EV invention | Flag off | Quant + Staff | Phase 3 |
| 7 | Read-only UI | Trade CTA | Revert UI | FE + Staff | API |
| 8 | Shadow cycle ≥1 successful run | Any order submit | Stop timer | Ops + Staff | Phase 3 |
| 9 | 30d harness produces metrics file | Harness invents fills | N/A | QA + Staff | archives |
| 10 | Readiness READY + grant | Cond./Not Ready | Pin prior release | CIO Ops | all |

---

## 6. Execution log (system of record)

### Phase 1 — Canonical SymbolDecisionObject
Status: COMPLETE  
Date: 2026-09-29  
Commit: bc9b38c1d  
Files changed: `scripts/lib/cross_asset/symbol_decision_object.py`, `persistence.py`, `assemble.py`, tests, docs  
Tests passed: 8/8 hermetic (`test_cross_asset_symbol_decision_object_20260929.py`)

### Phase 2 — Cross-system identity linking
Status: COMPLETE (scaffold)  
Date: 2026-09-29  
Commit: _(same cut)_  
Files changed: `assemble.py` (subject_guid / issuer_guid / hermes result_id join)  
Tests passed: assemble fixture links `ecb5ba89-test` + `rr_4a877da8499b`  
Note: Live store auto-join still Phase 4 event wiring.

### Phase 3 — Options routing layer (shadow)
Status: COMPLETE (scaffold)  
Date: 2026-09-29  
Commit: _(same cut)_  
Files changed: `expression_router.py`, shadow CLI  
Tests passed: Buy/Hold/Reentry/Sell routing + collar unavailable honesty  
Note: No chain pricing / EV yet.

### Phase 4 — Event-driven reevaluation
Status: PARTIAL  
Date: 2026-09-29  
Files changed: `events.py` (`CROSS_ASSET_SHADOW` flag)  
Tests passed: flag off no-write; flag on writes ledger  
Gap: not hooked into Hermes complete producer yet.

### Phase 5 — Missed opportunity ledger
Status: COMPLETE (scaffold)  
Date: 2026-09-29  
Files changed: `missed_opportunity_ledger.py`  
Tests passed: counterfactual row when chosen≠top

### Phase 6 — Cross-asset ranking engine
Status: PENDING (structural rank only; EV null)

### Phase 7 — UI integration
Status: PENDING

### Phase 8 — Shadow mode
Status: PARTIAL (CLI dry-run + apply-ledger proven; no systemd timer)

### Phase 9 — Production validation
Status: PARTIAL (replay harness returns INSUFFICIENT_DATA without archives — correct honesty)

### Phase 10 — Go-live
Status: NOT READY — see Readiness Report

---

## 7. Explicit non-goals (until READY)

- Auto-trading options or equity from this object.  
- Replacing OptionsDecisionPacket@v2 (we **embed/reference** it).  
- Inventing collar pricing before matrix support.  
- Treating hermetic PASS as OBSERVED_LIVE.
