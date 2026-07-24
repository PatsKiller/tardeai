# Trade AI Agentic MVL — Read Diligence and Today Plan

**Date:** 2026-07-24  
**Diligence snapshot:** 07:16 ET  
**Branch:** `feat/agentic-mvl-runtime-foundation`  
**PR:** #163  
**Pre-diligence head:** `961884ed90ef2c2369f857cccae897ef1d8c887d`  
**Status:** DRAFT / LAB-SHADOW FOUNDATION / NO ACTIVATION AUTHORIZATION

## 1. Parallel-project safety boundary

- Active Trader Session 1 is in its authorized 07:00–10:05 ET capture window, with autonomous closeout scheduled for 10:12 ET and bounded polling through 10:50 ET.
- `feat/active-trader-next` / PR #150 remains outside this work. No timer, marker, branch, SHA gate, capture runner, closeout runner, result, broker, Moomoo or observation state is changed here.
- PR #162 remains a separate Active Trader UI branch.
- This note is documentation-only on PR #163. It does not activate an agent, service, model lane, channel, scheduler, database migration or financial authority.

## 2. Read-only diligence completed

### Repository and review state

- PR #163 remains open, mergeable and draft.
- Focused `agentic-mvl-ci` completed successfully at the pre-diligence head.
- No PR comments, submitted reviews or unresolved inline review threads were present at the diligence snapshot.
- The repository-wide release-readiness workflow remains in its previously documented source-only validator failure class; no attempt was made to broaden scope or change unrelated validation code.

### Permission and authority review

The current MVL permission model correctly uses explicit allowlists and universal deterministic denials. Reflective agents and the OpenClaw/Hermes gateways cannot represent broker, order, trade, account/position write, approval, 2FA, secret, production-write, config-promotion, arbitrary-shell or service-control authority.

Current governed identities remain:

- Sentinel — SHADOW contract;
- Darwin — SHADOW contract;
- Nightly Reflection — SHADOW contract, not scheduled;
- Iris knowledge reviewer — SHADOW contract, not connected to the legacy Iris workflow;
- Hermes — DESIGNED and disabled;
- OpenClaw Concierge — DESIGNED and disabled.

No production OpenClaw or Hermes package, service, home, profile, channel, port or configuration has been inventoried or changed by this branch.

### Schema and migration review

The migration is additive under a separate `agentic_runtime` schema and limits run environments to LAB/SHADOW. Evidence tables are protected against UPDATE and DELETE; producer/reviewer and producer/scorer separation are database-constrained.

Important operational cautions:

1. `0001_mvl.down.sql` drops the complete schema with `CASCADE`; it is acceptable only for the isolated proof database and must never be treated as a routine production rollback.
2. Role creation, grants, canonical read-only views and production-write denial proofs are intentionally absent and remain prerequisites.
3. `CREATE SCHEMA IF NOT EXISTS` does not replace the required preflight proving that no prior evidence objects exist.
4. Migration proof must preserve sanitized schema inventory and must never expose the DSN or credentials.

### Runtime implementation review

The runtime proves the core governed lifecycle, but the following gaps must be closed before activation:

1. **Deadline enforcement:** `deadline_seconds` is validated in the registry but is not yet enforced during retrieval, model calls, tool calls, resume or completion.
2. **Concurrent journal safety:** the JSONL journal replays the file and then appends without an inter-process lock. It is suitable for deterministic tests and single-writer shadow proof, not concurrent service activation.
3. **Persistent tool evidence:** the file journal records allow/deny decisions, but the isolated Postgres persistence adapter and complete started/completed/result evidence path are not implemented.
4. **Provider enforcement:** provider family and model provenance are recorded, but real Local/Grok OAuth/ChatGPT OAuth wrappers, deadlines and no-fallback enforcement are not connected.
5. **Run failure handling:** the runtime has a `FAILED` terminal state but no complete operator-visible failure transition and persistence workflow yet.
6. **Data minimization:** secret-like keys are rejected, but the shadow file journal still records input and validation payloads. Before host activation, retention, field-level minimization and case-data classification must be reviewed.
7. **Operational status naming:** agent definitions may be marked SHADOW/enabled in the branch configuration while no service is running. Frontend and operator surfaces must distinguish `CONTRACT_ENABLED` from `SERVICE_ACTIVE`.

### Existing-system integration review

The governed MVL is still deliberately separate from the legacy agent system:

- not registered in `config/agents.json`;
- not routed by `scripts/agent_router.py`;
- not represented in `docs/AGENT_ROSTER.md`;
- not registered in `pipeline_registry.py` or the current pipeline health monitor;
- not scheduled by cron or systemd;
- not connected to existing OpenClaw agent homes or channels;
- not displayed in Command Center.

A naming and responsibility conflict must be resolved before integration: legacy Iris is the taxonomy/content-hygiene agent, while MVL Iris is an independent knowledge-lifecycle reviewer. They must receive distinct stable IDs and operator labels.

## 3. Safe work allowed during the Active Trader capture window

Until the Session 1 terminal closeout is available, safe work is limited to:

- repository and architecture read diligence;
- documentation on PR #163;
- non-mutating review of CI evidence;
- drafting host-inventory commands and acceptance checklists;
- designing, but not applying, database roles and grants;
- designing, but not activating, frontend and monitoring contracts.

Do not during this window:

- change PR #150 or its branch;
- touch capture/closeout timers, markers or runner state;
- install or upgrade OpenClaw, Hermes, Ollama, SDKs or packages;
- create/restart services or channels;
- apply a database migration;
- read production secrets;
- connect broker/account/order/2FA paths;
- mark PR #163 ready for review.

## 4. Recommended schedule for today

### 07:15–10:05 ET — documentation and design only

- preserve Active Trader capture isolation;
- complete repository-level diligence;
- finalize the host-inventory checklist;
- define the distinct MVL agent IDs and monitoring event contract;
- sketch the Command Center read-only run/evidence/review/score API contract.

### 10:05–10:50 ET — Active Trader closeout quiet period

- do not interfere with the closeout runner;
- wait for terminal evidence, SHA re-verification and cleanup;
- inspect only externally visible status such as PR head and operator email when available.

### 10:50–11:20 ET — terminal-state verification

Proceed only after one of these is recorded:

- Session 1 legitimately counted;
- terminal no-run/blocked result with cleanup complete;
- explicit evidence that the closeout did not finish and requires operator intervention.

Verify PR #150 head, closeout result, timer cleanup and whether Session 2 may be considered. Do not infer a count from one boolean.

### 11:20–12:15 ET — read-only host inventory

On `ms01-openclaw`, capture exact read-only evidence for:

- deployed Git SHA and dirty state;
- OpenClaw version, package provenance, home, service, port, channels and inherited environment;
- Hermes version, Python/package provenance, home/profile/MCP tools and auto-graft behavior;
- OpenAI SDK, Node, npm, Ollama and installed model inventory;
- pgvector version and live embedding provider/model/version provenance;
- agent-related cron and systemd units;
- existing database roles and canonical read-only views.

Do not upgrade, restart or edit anything during this inventory.

### 12:15–12:45 ET — inventory review and decision

Choose one documented path:

- **NO UPGRADE REQUIRED:** existing versions support isolated shadow contracts; or
- **SIDE-BY-SIDE CANDIDATE REQUIRED:** prepare separate homes, ports, identities and rollback evidence.

An in-place production upgrade is not an allowed path.

### 13:15–14:30 ET — isolated database proof, only if inventory is clean

- create or verify a dedicated canonical-view shadow reader;
- create an `agentic_runtime`-only writer in the isolated lab database;
- prove denied production-schema writes;
- run migration up/down/up in the isolated lab only;
- verify append-only triggers and reviewer/scorer separation;
- preserve sanitized evidence.

Stop if the target identity, host, database or permissions are ambiguous.

### 14:30–16:00 ET — implementation planning / bounded coding

Preferred order:

1. enforce runtime deadlines and terminal failure recording;
2. define the Postgres persistence adapter and complete tool-call evidence contract;
3. define concurrency strategy for journal/service activation;
4. resolve stable agent IDs, especially legacy Iris versus MVL Iris;
5. define monitoring events and read-only Command Center endpoints.

Do not activate services, schedules, channels or real provider calls today unless a separate reviewed authorization is recorded after the host and database proofs.

### 16:00–16:30 ET — end-of-day evidence review

Record:

- exact completed proofs;
- unresolved blockers;
- branch and CI state;
- whether OpenClaw/Hermes changes are unnecessary, planned side-by-side or still unknown;
- next authorized implementation slice;
- explicit statement that no production financial authority was created.

## 5. Immediate next implementation slices

### Slice A — runtime hardening

- enforce monotonic deadlines across retrieval, tools and model lanes;
- add explicit failure events and operator-visible failure explanations;
- add single-writer locking or move shadow durability to the isolated database before concurrency;
- add payload minimization and retention rules;
- test cancellation and deadline races.

### Slice B — isolated persistence and monitoring

- implement Postgres persistence for runs, artifacts, calls, reviews, scores and KB records;
- prove least-privilege roles;
- emit a stable monitoring event schema;
- integrate with pipeline health as a read-only status source, not as an authority bridge;
- preserve denied calls and provider failures as first-class evidence.

### Slice C — frontend

- add read-only Command Center pages for run list/detail, checkpoint, budget/deadline, retrieval, model/tool ledger, artifacts, reviews, disagreement, scores and exceptions;
- label environment and activation state explicitly;
- add cancel/resume only through the governed gateway;
- keep all promotion and financial actions absent.

### Slice D — shadow provider and acceptance proof

- implement isolated Local/Grok OAuth/ChatGPT OAuth wrappers with one call per lane and no fallback;
- wire Watch artifacts through Sentinel, independent review and Darwin scoring;
- run the 100-artifact acceptance population;
- keep Hermes and OpenClaw Concierge disabled until evidence gates pass.

## 6. Activation remains blocked

PR #163 must remain draft and unactivated until the following are reviewed and evidenced:

- host inventory;
- model/embedding drift resolution;
- dedicated least-privilege database roles;
- isolated migration proof;
- deadline and failure enforcement;
- persistent tool/retrieval/model provenance;
- monitoring and read-only frontend;
- provider wrappers with no fallback;
- 100-artifact acceptance population;
- explicit architecture-owner activation decision.

No result in this note authorizes OpenClaw/Hermes installation, production deployment, scheduler activation, channel connection, database migration outside the isolated lab, or any broker/order/approval/2FA action.

## 7. Isolated database proof — BLOCKED at preflight (13:15 ET)

No database connection or write was attempted. The required prerequisites were not evidenced in the repository or connected sources at preflight.

### Missing prerequisite evidence

1. **Completed read-only host inventory** for `ms01-openclaw`, including deployed SHA/dirty state, OpenClaw and Hermes versions/provenance, homes, services, ports, channels, inherited environment, SDK/runtime versions, Ollama models, pgvector, cron/systemd entries, and existing database roles/views.
2. **Documented shadow-upgrade decision** selecting either `NO UPGRADE REQUIRED` or `SIDE-BY-SIDE CANDIDATE REQUIRED`, with compatibility and rollback evidence.
3. **Unambiguous disposable LAB target**, including a non-production database identity/name and explicit confirmation that it contains no production data or pre-existing `agentic_runtime` evidence objects.
4. **Sanitized identity proof** for a dedicated canonical-view read-only shadow reader and a separate writer restricted to the `agentic_runtime` schema.
5. **Production-denial test plan and target**, identifying the non-sensitive schemas/tables against which denied writes can be proven without touching production data.
6. **Authorized migration executor** for the disposable LAB target, with a safe up/down/up window and confirmation that the destructive `DROP SCHEMA ... CASCADE` rollback is confined to that target.
7. **Evidence-preservation path**, naming the sanitized output location for role grants, schema inventory, denied-write results, trigger tests, and producer/reviewer/scorer separation tests.

### Disposition

`BLOCKED_PRECONDITION — NO DATABASE ACTION`

The migration, role creation, grants, denied-write tests, append-only trigger tests, and producer/reviewer/scorer separation tests remain unexecuted. PR #163 remains draft. No DSN, credential, secret, database connection, production schema, OpenClaw/Hermes service, broker, order, approval, or 2FA path was accessed or changed.
