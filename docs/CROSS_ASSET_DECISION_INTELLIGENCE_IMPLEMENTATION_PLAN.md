# Cross-Asset Decision Intelligence Implementation Plan

Status: PROPOSED — baseline before implementation
Owner: platform / investment-office engineering
as_of: 2026-09-29
Measured at: `5ba5d99ec06568f61f4db3a7010f01343023104`
Authority: advisory only; no broker, order, sizing, deployment, or trade authority

## Purpose

Build a single decision-routing layer that evaluates shares and defined option
expressions for every material investment signal. The system must be able to
answer, with durable evidence:

> For this thesis, at this timestamp and risk budget, which expression has the
> highest expected-value profile: shares, an option structure, or no action?

This program records recommendations only. It does not place orders, access a
broker, enable live execution, or change investment policy.

## Operating constraints

- `AGENTS.md` and `AI_WORK_POLICY.md` govern all changes.
- Local commits are checkpoints; remote synchronization is a separate operator action.
- Every stateful producer must be deterministic, idempotent, auditable, and fail closed.
- A model score is advisory and never substitutes for CIO or operator approval.
- Shadow mode may compare expressions but may not submit, size, or route orders.
- Historical replay must not use future observations or mutate live stores.

## Baseline checkpoint — before implementation

### Current state

| Capability | Status | Complexity | Risk | Dependencies | Evidence / finding |
|---|---|---:|---:|---|---|
| Portfolio holdings and position state | Partial | Medium | High | broker-ingest projections, account identity | Holdings feed exists; no universal expression comparison for every signal. |
| Watchlist and conviction signals | Partial | Medium | Medium | watchlist lifecycle, fused signals, thesis | Signals exist in multiple projections; no mandatory options comparison record. |
| CIO decisions | Existing | Large | High | CIO decision store, operator authority | Options CIO lifecycle exists; it is downstream of selected option proposals. |
| Hermes research | Existing | Large | Medium | research queue, provider router, durable results | Research can fill option thesis gaps; not yet a universal cross-asset trigger. |
| Aegis ensemble | Existing | Medium | Medium | inference jobs, model lanes | Advisory review exists; non-blocking and not a comparative equity/options optimizer. |
| Options desk | Partial | Large | High | Schwab chain cache, enterprise gates, thesis, CIO | Generates selected structures from selected universes; not every equity action. |
| Re-entry | Partial | Medium | Medium | exit universe, re-entry shared context, decision desk | Shared UI context exists; no required options expression comparison per re-entry signal. |
| Research state | Partial | Large | Medium | symbol thesis, Hermes, M2 projection | Multiple research stores and projections; linkage and freshness need a canonical projection. |
| Signal generation | Existing | Large | High | fused signals, watchlists, portfolio/re-entry | Signal vocabulary is distributed; no cross-asset routing contract. |
| Scheduler | Partial | Medium | High | lane registry, cron/systemd | Options monitor and thesis lifecycle are scheduled; cross-asset event triggers are absent. |
| Persistence layer | Partial | Large | High | JSONL stores, DB projections, identity registry | Symbol/thesis/options memory exists in separate stores; no canonical object or event ledger. |
| Historical outcomes | Partial | Large | High | paper outcomes, closed trades, assignment history | Options outcomes and equity outcomes are not joined into expression-level replay. |
| Cross-asset ranking | Missing | Large | High | canonical object, quote data, risk model, outcome model | No authoritative winner comparison for shares versus options. |
| Missed-opportunity ledger | Missing | Medium | Medium | signal events, routing contract, durable audit store | No durable record proving a comparison was expected but absent. |
| UI cross-asset surface | Missing | Large | Medium | API projection, Command Center v3 | Existing cards are options-desk cards, not a universal decision comparison. |
| Shadow mode | Missing | Medium | Medium | routing engine, replay fixtures, audit projection | No end-to-end cross-asset shadow projection. |

### What exists, what is duplicated, what is disconnected

Existing components include `symbol_thesis_cc`, re-entry shared context,
options thesis/CIO lifecycle, options decision packets, options memory envelopes,
watchlist projections, and options monitor schedules. These are valuable
building blocks and must be reused.

The principal duplication is symbol intelligence spread across thesis stores,
watchlist rows, re-entry payloads, options thesis records, CIO decisions,
research projections, and position/outcome stores. The principal disconnection
is that an equity signal can be created without a durable expression-comparison
event, and an options proposal can be created without proving that shares and
all appropriate option structures were compared.

## Target architecture

### Canonical contract

`SymbolDecisionObject@v1` is a versioned, read/write-by-owner projection. It is
not a replacement for source ledgers. It joins them by stable symbol/security
identity and records source references, freshness, and conflicts.

```text
SymbolDecisionObject@v1
├── identity
│   ├── symbol, security_guid, share_class, issuer_guid
│   ├── identity_status, source_refs
│   └── as_of
├── equity_thesis
│   ├── current, historical_versions, confidence
│   ├── invalidation_triggers, entry/add/reentry/exit zones
│   └── source_refs, as_of
├── research_state
│   ├── completed, missing, catalysts, event_calendar
│   ├── contrarian_evidence, freshness, source_refs
│   └── as_of
├── event_state
│   ├── price, iv, iv_rank, earnings, analyst, liquidity events
│   └── last_event_id, as_of
├── signal_state
│   ├── action, tags, score, confidence, horizon
│   ├── source, signal_id, emitted_at
│   └── as_of
├── position_state
│   ├── ownership, quantity, account, basis, previous ownership
│   ├── closed trades, wins, losses, assignments
│   └── as_of
├── options_state
│   ├── preferred/current/prior structures
│   ├── IV regime, liquidity, earnings restriction
│   ├── proposal refs, outcomes, validation freshness
│   └── as_of
├── cio_state
│   ├── decisions, decision changes, confidence trend
│   ├── approval state, decision GUIDs
│   └── as_of
├── historical_state
│   ├── equity outcomes, option outcomes, expression outcomes
│   └── replay references
├── expression_comparison
│   ├── candidates, scores, constraints, winner
│   ├── why_winner, why_rejected, recommendation_state
│   └── as_of, evaluation_id
└── audit_history
    ├── append-only events, prior hashes, actor, reason
    └── schema/version metadata
```

### Ownership and update paths

| Domain | Owner | Writes | Reads |
|---|---|---|---|
| Identity | identity registry / symbol resolver | identity links | every projection |
| Equity thesis | symbol-thesis producer | thesis versions | CIO, routing, UI |
| Research | Hermes/research producers | research results and gaps | thesis, CIO, routing |
| Signals | signal/watchlist/re-entry producers | signal events | routing, UI, audit |
| Positions | portfolio reconciliation | position snapshots/outcomes | routing, sizing constraints, UI |
| Options facts | options engine/validator | proposals, quotes, liquidity | routing, CIO, UI |
| CIO state | CIO decision writer | decisions and transitions | routing, approval surfaces |
| Comparison | cross-asset router | evaluations and winner | UI, shadow, replay, audit |
| Audit | append-only event writer | immutable receipts | readiness and investigations |

### Persistence mechanism

Phase 1 uses a pure Python contract plus append-only JSONL shadow projection,
with deterministic event IDs and hash-chain fields. The production database
projection is a later migration only after the contract, replay, and ownership
tests are green. No live store is mutated by tests.

### Required event triggers

`SIGNAL_CREATED`, `SIGNAL_CHANGED`, `PRICE_CHANGED`, `IV_CHANGED`,
`IV_RANK_CHANGED`, `EARNINGS_CHANGED`, `ANALYST_ACTION_CHANGED`,
`THESIS_CHANGED`, `REENTRY_CHANGED`, `CIO_DECISION_CHANGED`,
`LIQUIDITY_CHANGED`, `POSITION_CHANGED`, `OPTION_OUTCOME_RECORDED`.

## Implementation milestones

### Phase 1 — Canonical SymbolDecisionObject

Build the contract, normalization, deterministic IDs, append-only shadow writer,
and read projection. The first implementation must be pure and testable without
DB, broker, or network access.

Pass: schema validates; unknown/ambiguous identity fails closed; replay is deterministic; append-only preservation tests pass.

Fail: malformed source is silently accepted, duplicate events are written, or a test reaches a live store.

Rollback: revert the local commit; no production schema or scheduler mutation exists in Phase 1.

Owner: platform intelligence. Dependencies: existing identity/thesis contracts.

### Phase 2 — Cross-system identity linking

Join portfolio, watchlist, re-entry, thesis, research, CIO, and option records by
stable identity. Produce explicit unresolved/conflicted rows.

Pass: every material source row has a traceable identity or an auditable unresolved state.

Fail: symbol-only joins silently merge issuers or lose source lineage.

Rollback: disable the projection consumer; retain source ledgers unchanged.

Owner: identity/data platform. Dependencies: Phase 1, identity registry.

### Phase 3 — Options routing layer

For each signal, generate applicable comparisons: shares, CSP, long call, call
spread, covered call, protective put, collar, put spread, credit spread, and no action.

Pass: routing coverage exists for every supported signal type; hard liquidity/earnings/sizing gates remain fail closed.

Fail: the router produces an option recommendation without required chain facts or treats a model score as approval.

Rollback: feature flag routing to shadow-only; options desk remains unchanged.

Owner: options/platform. Dependencies: Phase 1–2, existing options economics.

### Phase 4 — Event-driven reevaluation

Add idempotent trigger intake and evaluation scheduling. Re-evaluate on every
required state change with debounce and provenance.

Pass: each trigger creates one deterministic evaluation or a durable refusal.

Fail: trigger loss, duplicate evaluation, or stale quote use without explicit status.

Rollback: stop the new consumer; source event streams remain intact.

Owner: platform scheduling. Dependencies: Phase 1–3, lane registry.

### Phase 5 — Missed-opportunity ledger

Record expected comparisons, generated comparisons, blocked comparisons, and
missing comparisons with exact reasons and timestamps.

Pass: coverage denominator and missed-opportunity counts reconcile.

Fail: “no proposal” cannot be distinguished from “not evaluated.”

Rollback: shadow ledger only; no action path depends on it.

Owner: QA/data governance. Dependencies: trigger and routing events.

### Phase 6 — Cross-asset ranking engine

Rank expressions by risk-adjusted expected value and capital efficiency, subject
to policy, account, liquidity, event, and thesis constraints.

Pass: deterministic ranking fixtures, explicit uncertainty, and no policy bypass.

Fail: ranking changes without input changes or recommends blocked structures.

Rollback: publish comparisons without a winner; retain evidence.

Owner: CIO operations with quantitative review. Dependencies: outcomes and routing.

### Phase 7 — UI integration

Expose source signal, all tested expressions, winner, blockers, freshness, and
next review on a unified decision surface.

Pass: UI/API agree with projection and show unavailable/conflicted states.

Fail: UI labels a blocked or estimated quote as executable.

Rollback: hide the new surface behind a flag.

Owner: Command Center. Dependencies: stable API projection.

### Phase 8 — Shadow mode

Run continuously without trades. Compare every qualifying signal across required
structures and write only shadow records.

Pass: 100% signal coverage or an explicit durable refusal; zero broker/order calls.

Fail: missing signal, missing comparison, live side effect, or unbounded queue.

Rollback: disable shadow consumer and preserve audit files.

Owner: QA/CIO operations. Dependencies: Phases 1–7.

### Phase 9 — Production validation

Replay 30/60/90-day data, compare expression outcomes, inspect false positives,
false negatives, stale data, and disagreement rates.

Pass: all metrics reproducible and reviewed; no unresolved high-risk data lineage gaps.

Fail: future leakage, non-reproducible rankings, or unexplained missing coverage.

Rollback: remain in shadow mode.

Owner: QA and CIO operations. Dependencies: historical fixtures and outcomes.

### Phase 10 — Go-live

Go-live means advisory projection only unless a separate operator-approved
execution program exists. No deployment or broker action is part of this tranche.

Pass: readiness report is `READY` or `CONDITIONAL` with explicit operator-owned conditions.

Fail: any authority, persistence, safety, or replay gate fails.

Rollback: disable feature flag and return to existing options desk.

Owner: operator/CIO governance. Dependencies: all prior phases and independent review.

## Executable backlog

| ID | Title | Purpose | Files / surfaces | Tests | Risk | Reviewer |
|---|---|---|---|---|---|---|
| CA-001 | Define `SymbolDecisionObject@v1` | Establish canonical contract and normalization | `scripts/lib/cross_asset_decision.py` | schema, malformed, identity | High | platform + data |
| CA-002 | Append-only shadow store | Persist evaluations without live DB writes | `scripts/lib/cross_asset_store.py` | idempotency, hash chain, preservation | High | data governance |
| CA-003 | Signal-to-expression router | Map actions to candidate structures | `scripts/lib/cross_asset_router.py` | matrix and refusal tests | High | options + CIO |
| CA-004 | Event trigger envelope | Normalize state changes and deterministic evaluation IDs | `scripts/lib/cross_asset_events.py` | dedupe, ordering, stale event tests | High | platform |
| CA-005 | Missed-opportunity ledger | Prove expected versus actual coverage | `scripts/lib/cross_asset_coverage.py` | denominator/reconciliation tests | Medium | QA |
| CA-006 | Historical replay harness | Run 30/60/90-day deterministic replay | `scripts/cross_asset_replay.py` | no-future-leakage, repeatability | High | QA |
| CA-007 | Shadow scheduler adapter | Consume approved signal events without side effects | `scripts/cross_asset_shadow_runner.py`, lane registry | scheduler and no-mutation tests | High | operations |
| CA-008 | API projection | Serve unified comparison objects | `scripts/api_v2.py` or dedicated projection route | API contract tests | Medium | API owner |
| CA-009 | Command Center surface | Show cross-asset comparison and blockers | `apps/command-center-v3/src/...` | TypeScript/UI tests | Medium | frontend |
| CA-010 | Readiness evidence | Generate metrics and recommendation | `scripts/cross_asset_readiness.py`, docs | evidence reconciliation | Medium | QA/CIO |

## Phase 1 implementation record

Status: COMPLETE
Date: 2026-09-29
Commit: `4e39b4103193784950377d8c00a5fc1d05c096fd`
Files changed:

- `scripts/lib/cross_asset_decision.py`
- `tests/test_cross_asset_decision_intelligence.py`
- `scripts/run_cio_hardening_ci.py`
- `docs/CROSS_ASSET_DECISION_INTELLIGENCE_IMPLEMENTATION_PLAN.md`
- `docs/CROSS_ASSET_DECISION_INTELLIGENCE_TEST_PLAN.md`

Tests passed:

- `python3 -m pytest -q tests/test_cross_asset_decision_intelligence.py` — 6 passed
- `python3 -m py_compile scripts/lib/cross_asset_decision.py tests/test_cross_asset_decision_intelligence.py`
- Ruff via `/home/johnclaw/tradeai-wt-comms-gateway-phase0/.venv/bin/ruff` — passed
- `python3 scripts/check_test_coverage.py --fail-on-new` — new tests 0, registered by CI
- `git diff --check` — passed

Evidence: the Phase 1 module is broker-free, sets `financial_action=false`,
fails closed on unknown signals and identity mismatch, generates the required
comparison candidates, and writes idempotently to an explicit append-only shadow
path. No production store, broker, scheduler, or live endpoint was touched.

## Change log

| Date | Status | Evidence |
|---|---|---|
| 2026-09-29 | BASELINE | This document created before implementation at local HEAD `5ba5d99e`. |
| 2026-09-29 | COMPLETE | Phase 1 committed at `4e39b4103`; targeted tests and static checks passed. |
| 2026-09-29 | COMPLETE | Phase 2 identity linking, Phase 3 routing, Phase 5 coverage accounting, and Phase 6 deterministic ranking primitives committed at `511d8dda2`; 9 tests passed. |
| 2026-09-29 | COMPLETE | Offline replay command committed at `1d440dd23`; 10 tests passed. This is a replay primitive, not historical production validation. |
| 2026-09-29 | COMPLETE | Deterministic shadow runner committed at `f1d5b1546`; 11 tests passed. This is offline shadow mode, not continuous production shadow mode. |

## Post-baseline implementation status

| Phase | Status | Commit / evidence | Remaining work |
|---|---|---|---|
| 1 Canonical object | COMPLETE | `4e39b4103`; contract/store tests | Production projection integration |
| 2 Identity linking | COMPLETE — library slice | `511d8dda2`; conflict-preserving join tests | Connect every live source and identity registry |
| 3 Options routing | COMPLETE — library slice | `511d8dda2`; 15-signal matrix and hard-block tests | Integrate with live signal producers and options facts |
| 4 Event reevaluation | NOT COMPLETE | Event envelope/replay primitives only | Register event producers and a governed consumer lane |
| 5 Missed-opportunity ledger | COMPLETE — initial coverage row | `511d8dda2`; denominator test | Durable ledger producer and source reconciliation |
| 6 Cross-asset ranking | COMPLETE — deterministic fact-gated ranking | `511d8dda2`; blocked candidates excluded | Quantitative model calibration and outcome joins |
| 7 UI integration | NOT STARTED | No runtime/API/UI change | API projection, UI, route tests |
| 8 Shadow mode | COMPLETE — offline harness | `f1d5b1546`; idempotent shadow receipt and no-action assertion | Continuous scheduler-backed shadow run |
| 9 Production validation | NOT STARTED | No historical production source replayed | 30/60/90-day replay metrics |
| 10 Go-live | NOT READY | Cannot recommend before phases 4, 7, 8, 9 | Independent readiness review |

## Scope boundary and blocker

The local API socket was unavailable from this execution environment (`curl` to
localhost:7777 failed with `Operation not permitted`) and the current crontab
was unreadable (`Permission denied`). Therefore the new replay command has been
validated only on caller-supplied fixtures. I will not claim live signal
coverage, continuous shadow mode, historical metrics, or production readiness
without those observable inputs.
