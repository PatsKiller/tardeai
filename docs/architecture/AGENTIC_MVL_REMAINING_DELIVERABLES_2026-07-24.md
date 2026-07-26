# Agentic MVL Remaining Deliverables — 2026-07-24

**PR:** #163  
**Mode:** DRAFT / LAB / SHADOW  
**Financial authority:** DENIED

## Gate 1 — classify the user-owned PostgreSQL LAB candidate

- inventory databases, owners, sizes, schemas and relation counts on `127.0.0.1:5433` without reading row contents;
- confirm the selected database is disposable and contains no production-derived, sensitive or operator data;
- confirm no existing `agentic_runtime` evidence requires preservation;
- confirm role-creation authority, cleanup scope and non-repository credential delivery;
- record `PASS_LAB_CANDIDATE` or `BLOCKED_LAB_CLASSIFICATION`.

## Gate 2 — provision least-privilege LAB identities

- create or verify `agentic_lab_migrator`, restricted to the disposable LAB and absent from runtime configuration;
- create or verify `trade_ai_shadow_ro`, with LOGIN and SELECT only on approved synthetic canonical views;
- create or verify `agentic_runtime_lab_rw`, with LOGIN and required DML only inside `agentic_runtime` and no CREATE or writes elsewhere;
- create synthetic canonical views and a synthetic protected denial-test schema;
- preserve sanitized ownership, role attributes, grants and cleanup commands.

## Gate 3 — prove migration and database isolation

- apply `0001_mvl.up.sql` only in the disposable LAB;
- verify exactly eight expected tables, owners and grants;
- verify append-only UPDATE/DELETE rejection on evidence tables;
- verify producer/reviewer and producer/scorer separation;
- verify reader SELECT success and all write denial;
- verify writer DML only in `agentic_runtime` and denied writes elsewhere;
- apply `0001_mvl.down.sql`, prove clean isolated removal, and replay up;
- preserve migration and schema hashes plus sanitized evidence;
- authorize persistence implementation only after a complete PASS.

## Slice 1 — isolated Postgres persistence

- implement persistence adapters for runs, artifacts, retrieval evidence, tool calls, reviews, scores, lessons, cases and chunks;
- enforce LAB/SHADOW environment restrictions at adapter boundaries;
- use the runtime writer only; never use the migration executor in application code;
- add isolated integration tests and failure/rollback behavior.

## Slice 2 — complete evidence lifecycle and concurrency

- record tool request, policy decision, allow/deny, execution start, terminal result, result hash, latency, failure and cancellation;
- make denied calls and provider failures first-class evidence;
- replace JSONL as the authoritative concurrent store;
- retain a read-only deterministic JSONL export/replay format;
- define retention, minimization and case-data classification rules.

## Slice 3 — stable identities and monitoring contracts

- namespace legacy and MVL agent identifiers;
- distinguish legacy taxonomy Iris from MVL knowledge-review Iris;
- distinguish contract-enabled, service-active and activation-authorized states;
- define versioned events for run state, checkpoints, budgets, deadlines, retrieval, tool decisions, artifacts, reviews, disagreement, scores, cancellation, resume and failure;
- integrate pipeline health as read-only telemetry, never as an authority bridge.

## Slice 4 — read-only Command Center contracts and UI

- define read-only APIs for run list/detail, checkpoints, budgets, retrieval, tool ledger, artifacts, reviews, disagreements, scores and exceptions;
- prohibit mutation, provider execution, promotion and financial-action endpoints;
- build desktop and narrow frontend views with explicit LAB/SHADOW and service-state labels;
- render and test empty, stale, failed, cancelled, disagreement and insufficient-evidence states.

## Slice 5 — provider wrappers and knowledge persistence

- implement isolated Local, Grok OAuth and ChatGPT OAuth wrappers;
- enforce one bounded call per lane, deadlines, exact provenance and no silent fallback;
- resolve effective model-routing and embedding-version drift;
- persist KB lessons, cases, chunks and retrieval evidence through the isolated schema;
- keep vector activation separately gated until the pgvector/storage decision is documented.

## Slice 6 — Darwin, Reflection and Iris lifecycle

- join immutable artifacts to later outcomes;
- implement Darwin scorecards and confidence calibration;
- implement bounded Nightly Reflection without scheduling or activation by default;
- implement independent MVL Iris adjudication for candidate, ratified, disputed and retired lessons;
- preserve contradiction and counterevidence links.

## Acceptance and activation gates

- run at least 100 shadow artifacts, including at least 20 known-bad cases;
- achieve at least 95% retrieval and scoring coverage;
- prove zero deterministic-failure releases;
- prove zero broker, order, approval, 2FA and production-configuration calls;
- prove cancellation, resume, deadline, tamper, provider-failure and disagreement behavior;
- complete a host-side shadow smoke and monitoring review;
- obtain explicit architecture-owner activation authorization;
- keep PR #163 draft until every prerequisite is evidenced.

## Host and operational blockers before activation

- reconcile or park the dirty live repository worktree and establish a reproducible deployed SHA;
- locate and restore-test the current database backup regimen;
- remediate the duplicate restarting user `portfolio-server.service`;
- review Tailscale/firewall exposure for Ollama and metrics ports;
- snapshot the Hermes venv before any future upgrade;
- triage failed Hermes and Iris units without conflating them with the MVL runtime;
- resolve the broken disabled Hermes gateway unit;
- decide how embeddings are stored and whether pgvector is needed;
- do not combine these maintenance changes with the isolated database proof.
