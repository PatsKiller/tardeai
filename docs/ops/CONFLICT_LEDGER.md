# Conflict ledger, operator API and CIO integration

Status: LOCAL SOURCE; owner integrations and runtime acceptance pending

Design-Task: DSN-20261024-conflicts-P2-T1

`ConflictLedger` is the one append-only writer to
`data/conflicts/conflict_events.jsonl`. Each event contains the subject, finding,
time and sequence; `ConflictRecord@v1` is rebuilt from those events. Invalid or
truncated history fails closed. Polls with unchanged findings append nothing.
Security state transitions require a CIO memory delivery; durable sink receipts
and immutable event IDs prevent writes on every poll. The sink uses the existing
SecurityResearchSpine API with silo=cio, tag=conflict and security GUID.

Decisions contain server-derived actor, reason, evidence, expiry and expected
record revision. T0/T1 facts and safety cannot be picked by a decision; numeric
and schedule defects require repair at their source. A decision advances DECIDED,
which still flags until a valid engine re-evaluation clears it. Never-auto
findings are retained. Missing producers, failed opinions and R15 confirmation
observations cannot clear a flag. A review queue transition requires an actual
request receipt. `complete_review` records the decision, calls the producer's
update callback and verifies exact persisted readback before review_completed.
It never assigns a model draft to the CIO's canonical stance.

The SQL migration and `postgres_sink(connection_factory)` are source-only. PG
mirroring defaults off and needs explicit dependency injection plus operator
migration; no code here loads credentials or runs a migration. Proposed authority,
backup and completeness rows are under `config/proposals/conflict_ledger/` for
their current file owners. Retention is 400 days with archival, never deletion
by this module. Actual backup coverage remains NONE until a real backup source
and restore proof exist; the proposal does not assert coverage.

## Read and decision contracts

`GET /api/v3/conflicts` returns `ConflictCollection@v1` with bounded `records`,
`total`, `offset`; filters include subject_kind, subject_id, state and kind.
Summaries omit full history and the duplicated embedded finding. Selected
`GET /api/v3/conflicts/{encoded-key}` returns the full Record with history and
decision. The module handler is `scripts.lib.conflicts.api.handle`; the current
route owner must register it. No v2 alias is needed.

`POST /api/v3/conflicts/{encoded-key}/decision` accepts expected_revision,
chosen_side, reason, evidence_refs and expires_at. It checks the authenticated
operator tailnet identity, serve-proxy listener and same-origin CSRF. Agents,
n8n and service tokens are refused. Writer activation defaults false; a body or
claimed actor cannot activate it. No endpoint changes broker behavior.

`records_section` and `data_error_section` own lifecycle filtering, paging,
headline order, gaps and record conversion. Missing/corrupt ledgers remain gaps.
`sections_for_guids(root, guids)` reads the ledger once for Watch batch attachment
as `row.conflict_section`; no per-row API requests or page classifiers are needed.
`approval_rows` gives W11 version-hashed NEEDS_OPERATOR documents; audit
dispositions are separate from actual conflict decisions.

## Runner and CIO owner hooks

`scripts/conflict_resolver.py --dry-run --state-root ROOT` reads canonical W1
inputs and existing Watch projections. `--input-file` is explicit fixture replay
only and must not be scheduler-admitted. Dry-run creates no lock, receipt or
ledger. `--shadow` holds `ROOT/data/conflicts/conflict_resolver.lock`, writes
ledger/comparison artifacts and a standard LaneRunReceipt@v2. Its business phase
is shadow while executor mode is live; notifications are always zero. One real
comparison report justifies produced_count=1, including an unchanged result.
Duplicate/uncertain run IDs refuse before another observation. A failure writes
a failed standard receipt and never advances successful freshness.

The registered n8n argv, outer lock, closed environment and measured timeout
belong to W8. The complete 281-row canonical runtime remains NOT_MEASURED, and
fixture runs do not count toward two trading days of shadow evidence. There is
no live or notification sender in this runner.

`cio_conflicts` exposes one context for review prompts, daily briefs, Ask answers,
conviction promotion and digest content. `cio_agent_brief.build_brief` and its
existing Telegram renderer now read that digest, show recorded reasons and group
operator items without claiming DECIDED is CLEARED. Ask, review-prompt and actual
conviction-consumer hooks still require their owners; a helper alone does not
establish DESIGN section 12 completion.
`ask_context_rows(root, security_guid)` supplies current read-only recall context;
the proposed minimal Ask owner patch and exact-base SHA manifest are
`config/proposals/conflict_ledger/ask_owner_hook.patch` and
`ask_owner_hook.manifest.json`. They target frozen Ask head `87a6d1d0fbf168a804792782f4eb4d97edc6cefd`
and must be applied by its owner after the frozen W10 dependency is public. Three
hermetic proposal tests verify GUID binding, named gaps and no poll writes; the
owner must also run the Ask affected and pending/provider-spy regressions. The
actual Ask source files are unchanged here.
The C3 completion owner must provide a real compared-input writer/readback;
immutable provider artifacts must not be rewritten or given forged authorization.
Existing PUBLISHED/TTL acquisition closure is not proof of a conflict decision.

## Current verification boundaries

Hermetic tests prove lifecycle, API identity/CSRF/version/expiry, memory-outbox
recovery, source-update readback, write-free dry-run, real shadow comparison and
per-attempt receipt, distinct-run hysteresis and reset. All tests use disposable
roots and fake sinks. No provider send, production decision/write, queue drain,
broker call, migration, lane activation or notification is performed.

Runtime owner hooks, registered store/backup/completeness edges, final rulebook
ratification, the exact captured 31-row golden replay, actual UI tap evidence and
live flips remain separately evidenced dependencies. W9/W7/W4 own UI proof.
