# CODEX IMPLEMENTATION PROGRAM v1.1

Status:      ACTIVE
as_of:       2026-07-22T23:51:03Z
Measured at: efcc51365 / not measured

## Active Trader Next · Moomoo Live Momentum Scalp · Trade AI Architecture v3.3

**Repository:** `PatsKiller/tardeai`
**Controlling architecture:** `docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md`
**Execution style:** staged, additive, quasi-parallel, evidence-gated
**Primary rule:** Do not reinterpret financial guardrails. Implement the architecture exactly.
**Live authority:** architecture-owner approved only through the v3.3 session-scoped authorization envelope.

---

# -1. NIGHT-RUN ORCHESTRATION CONTRACT

This program is designed for a later operator-issued start prompt.

Do not start implementation merely because this document exists.

## Execution branch

```text
feat/active-trader-next
```

Never commit implementation stages directly to `main`.

## Sequential behavior

The controller executes one stage at a time.

A stage is green only after:

1. plan written;
2. code complete;
3. tests green;
4. current `/v3` regression green;
5. closeout written;
6. architecture compliance checked;
7. stage committed;
8. branch pushed;
9. Drive sync complete;
10. local/GitHub/Drive hashes match;
11. checkpoint updated.

Only then may the next stage begin.

## Failure behavior

On any failed assertion:

- stop;
- do not begin another stage;
- preserve logs and worktree;
- write failure closeout;
- push safe diagnostic artifacts;
- sync available evidence to Drive;
- send operator email;
- record exact resume command.

## Required unattended preflight

```text
GitHub push test
Google Drive create/update/hash test
Gmail operator-send test
Bitwarden lab placeholder-create test
test database migration rollback
disk and time budget
no live broker credentials mounted
no production deploy credentials mounted
all live feature flags false
```

The night run cannot begin if Gmail or Drive verification fails.

## Required outputs per stage

```text
stage-XX-plan.md
stage-XX-closeout.md
stage-XX-tests.json
stage-XX-changes.txt
stage-XX-drive-manifest.json
```

## Final output

```text
FINAL_RUN_REPORT.md
ARCHITECTURE_COMPLIANCE.md
OPERATOR_TODO.md
CREDENTIAL_REQUIREMENTS.md
ROLLBACK.md
DRIVE_FINAL_MANIFEST.json
```

Send the operator an email with the PR, Drive folder, commits, tests, TODOs, credential requirements, litmus verdict, and next action.

# 0. OPERATING INSTRUCTIONS FOR CODEX

Before editing:

1. Read the controlling architecture in full.
2. Read repository `AGENTS.md` files from root to target directory.
3. Verify the repository path, branch, current SHA and working tree.
4. Inventory current services, routes, schemas, feature flags, broker adapters and test commands.
5. Produce an implementation plan for the current stage.
6. Do not begin a later stage.
7. Do not touch unrelated local changes.
8. Use additive schema and compatibility views.
9. Preserve `/v3`.
10. Never enable a live feature flag during build stages.
11. Never use real credentials in tests.
12. Never queue, submit, modify or cancel a real order during stages 0–13.
13. Every stage ends with tests, evidence, changed-file list, SHA and rollback.
14. Stop when a stage acceptance gate fails.

OpenAI's recommended pattern for large Codex work is to begin with a plan, provide repository guidance and reliable tests, and keep higher-risk actions explicit. Follow that pattern.

## Mandatory safety assertions

At every stage closeout:

```text
REAL ORDER QUEUED: NO
REAL ORDER SUBMITTED: NO
REAL ORDER MODIFIED: NO
REAL ORDER CANCELLED: NO
REAL 2FA REQUESTED: NO
PRODUCTION SECRET READ: NO
PRODUCTION GUARDRAIL CHANGED: NO
/V3 ROUTE REMOVED OR REPLACED: NO
```

Stage 14 has a different closeout because it is the controlled live-canary stage.

---

# STAGE 0 — BASELINE AND READ-ONLY ARCHITECT LITMUS REVIEW

## Goal

Map the repository and run a no-write architecture challenge.

## Required artifacts

```text
ACTIVE_TRADER_STAGE0_BASELINE.md
ACTIVE_TRADER_ROUTE_API_DB_MAP.md
ACTIVE_TRADER_BROKER_ACCOUNT_INVENTORY.md
ACTIVE_TRADER_CURRENT_GUARDRAILS.md
ACTIVE_TRADER_LITMUS_REVIEW.md
```

The litmus reviewer receives read-only access and must prove it cannot write.

A FAIL pauses the night run.

---

# STAGE 1 — ADDITIVE SCHEMA, CONTRACTS, FLAGS, AND CHECKPOINTING

Implement additive tables and typed contracts for:

```text
active trader sessions and authorizations
broker capabilities
broker rejection events
feature flags
notifications
journal
Drive sync manifest
night-run checkpoint
```

Implement rollback migrations.

All flags default OFF except development read-only visibility.

---

# STAGE 2 — BROKER ACCOUNT DISCOVERY AND CAPABILITY REGISTRY

Discover all configured Alpaca, Moomoo, and Schwab accounts.

Implement:

- account registry adapter contract;
- capability probe;
- per-account capability expiry;
- typed unsupported results;
- current account eligibility projection.

No order submission.

Tests include unsupported flatten, unknown capability, stale OAuth, and multi-account discovery.

---

# STAGE 3 — BROKER REJECTION CLASSIFIER, NOTIFICATIONS, AND FALLBACK POLICY

Implement normalized rejection codes and fixtures, including:

```text
SECURITY_REQUIRES_BROKER_ASSISTANCE
ELECTRONIC_ENTRY_NOT_ALLOWED
LOW_PRICE_OR_MICROCAP_RESTRICTION
SECURITY_NOT_DAY_TRADE_ELIGIBLE
```

Implement:

- blocking UI notification projection;
- journal event;
- Telegram/email adapters where configured;
- primary/fallback account policy;
- duplicate-fill prevention;
- new-2FA requirement for unapproved alternates.

Use mocks and captured/synthetic responses only.

---

# STAGE 4 — ACTIVE TRADER READ API

Implement additive `/api/v3/active-trader` read endpoints for:

- session;
- candidates;
- symbol;
- accounts;
- capabilities;
- orders;
- positions;
- P&L;
- rejections;
- journal;
- features;
- parity.

No write code reachable.

---

# STAGE 5 — MOOMOO DATA GATEWAY, REPLAY, AND RATE GOVERNOR

Implement data-only Moomoo services, feature snapshots, replay, sequence state, subscription governance, and account-level place/modify token buckets.

Do not implement the old 750 ms loop.

No live trade unlock.

---

# STAGE 6 — `/V3-NEXT` READ-ONLY ACTIVE TRADER UI

Create a separate bundle.

Implement:

- classic/next navigation;
- session strip;
- prime queue;
- full pre-trade ticket;
- working-order ticket;
- in-trade ticket and P&L;
- chart;
- Level 2;
- time and sales;
- accounts;
- rejections;
- journal;
- feature-control modal in read-only mode.

Do not rewrite `TradingHub`.

---

# STAGE 7 — SESSION BUILDER, ACCOUNT CHECKBOXES, AND FEATURE MODAL

Implement:

- account PRIMARY/FALLBACK/DISABLED choices;
- shares/notional/risk sizing;
- per-account quantity;
- quick-add preset configuration;
- risk and session limits;
- save/version;
- feature flags for OFF/READ_ONLY/SHADOW/SIMULATION.

No 2FA and no order.

---

# STAGE 8 — SESSION 2FA, AUTHORIZATION, AND LIVE-INACTIVE ACTION CONTRACTS

Implement one-time session 2FA and hash binding.

Implement action contracts for:

```text
add
cancel
cancel all entries
cancel symbol non-protective
sell smart
flatten
broker fallback
```

Live flag remains false, and adapters are mocks/simulation only.

---

# STAGE 9 — SHADOW PRIME, FIRE, RES/RRS, AND JOURNAL

Implement the deterministic shadow engine and complete event journal.

Include broker rejection/fallback simulations.

Zero orders.

Require at least 60 scored fires before promotion.

---

# STAGE 10 — MULTI-BROKER SIMULATION EXECUTION

Implement simulation child orders for all available test environments/adapters.

Exercise:

- primary and fallback accounts;
- quick adds 100/200/500/1000 in shares and dollars;
- partial fills;
- smart-limit entry;
- cancel;
- protected cancel-all;
- sell smart;
- broker-specific flatten translation;
- rate limits;
- restart and reconciliation.

No real broker order.

---

# STAGE 11 — JOURNAL, DARWIN, DRIVE, EMAIL, AND BITWARDEN SCAFFOLDING

Implement:

- complete replay timeline;
- outcome scoring;
- stage checkpoint controller;
- GitHub stage commit/push;
- Drive idempotent sync and hash verification;
- Gmail completion/failure notification;
- credential requirement manifest;
- Bitwarden lab placeholder records;
- operator TODO.

Never write real credential values.

---

# STAGE 12 — FINAL READ-ONLY ARCHITECT LITMUS REVIEW

Provide the full branch, diffs, tests, security evidence, schemas, UI screenshots, capability matrix, Drive manifests, and rollback.

The reviewer:

- has read-only access;
- produces one report;
- makes no edits;
- returns PASS, CONDITIONAL_PASS, or FAIL.

FAIL stops the program.

---

# STAGE 13 — DUAL OPERATION READINESS

Prove:

- `/v3` unchanged;
- `/v3-next` switch and rollback;
- old/new data parity;
- all live flags off;
- draft PR current;
- Drive and GitHub complete;
- operator completion email delivered.

The unattended night run stops here.

---

# STAGE 14 — CONTROLLED LIVE CANARY

Do not run this stage under the unattended implementation prompt.

It requires a later operator-issued start prompt tied to:

- exact reviewed SHA;
- selected broker/accounts;
- selected symbols/universe;
- risk envelope;
- capability proof;
- live credentials;
- feature flags;
- session 2FA;
- operator presence.

# FINAL CODEX CLOSEOUT FORMAT

```text
STAGE:
START SHA:
END SHA:
BRANCH:
FILES CHANGED:
MIGRATIONS:
SERVICES:
ROUTES:
TESTS:
BUILD:
DEPLOYED:
FEATURE FLAGS:
ROLLBACK:
OPEN RISKS:

REAL ORDER QUEUED:
REAL ORDER SUBMITTED:
REAL ORDER MODIFIED:
REAL ORDER CANCELLED:
REAL 2FA REQUESTED:
PRODUCTION SECRET READ:
PRODUCTION GUARDRAIL CHANGED:
/V3 ROUTE REMOVED OR REPLACED:
STAGE COMMIT:
GITHUB PUSH:
DRIVE SYNC:
DRIVE HASH VERIFIED:
CHECKPOINT:
OPERATOR EMAIL:
BITWARDEN PLACEHOLDERS:
OPERATOR TODO:
LITMUS REVIEW VERDICT:
```
