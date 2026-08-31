# CODEX IMPLEMENTATION PROGRAM v1.0

Status:      ACTIVE
as_of:       2026-07-22T18:56:48-04:00
Measured at: efcc51365 / not measured

## Active Trader Next · Moomoo Live Momentum Scalp · Trade AI Architecture v3.2

**Repository:** `PatsKiller/tardeai`  
**Controlling architecture:** `docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_2.md`  
**Execution style:** staged, additive, quasi-parallel, evidence-gated  
**Primary rule:** Do not reinterpret financial guardrails. Implement the architecture exactly.  
**Live authority:** architecture-owner approved only through the v3.2 session-scoped authorization envelope.

---

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
12. Never queue, submit, modify or cancel a real order during stages 0–9.
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

Stage 10 has a different closeout because it is the controlled live-canary stage.

---

# STAGE 0 — BASELINE, MAP, AND TEST HARNESS

## Goal

Create no product behavior. Produce the exact implementation map and regression harness.

## Required investigation

- Current `apps/command-center-v3` route and build structure.
- `TradingHub.tsx`, existing `Scalp` tab, Broker Orders active-trader concepts, Journal and execution-quality surfaces.
- Current server entry points and `/api/v2` routes.
- Current Moomoo code, package state and OpenD services.
- Current broker/account registry.
- Current approval and 2FA implementation.
- Current journal/event/outbox implementation.
- Current DB migrations.
- Current feature-flag implementation.
- Current tests and deployment commands.
- Unrelated dirty files.

## Deliverables

```text
docs/implementation/ACTIVE_TRADER_STAGE0_BASELINE.md
docs/implementation/ACTIVE_TRADER_ROUTE_AND_API_MAP.md
docs/implementation/ACTIVE_TRADER_DB_MAP.md
docs/implementation/ACTIVE_TRADER_SECURITY_BOUNDARY.md
```

Add regression fixtures for:

- FATN invented entry;
- no verified ticket;
- stale data;
- account ineligible;
- duplicate session activation;
- changed draft after authorization.

## Acceptance

No runtime behavior changed.

---

# STAGE 1 — ADDITIVE CONTRACTS, SCHEMA, AND FLAGS

## Goal

Create server-side contracts without UI or broker writes.

## Additive schema

Implement versioned migrations for:

```text
active_trader_session_drafts
active_trader_session_authorizations
active_trader_session_accounts
active_trader_order_intents
active_trader_position_states
active_trader_journal_events
active_trader_score_snapshots
active_trader_parity_checks
```

Implement environment constraints that separate:

```text
SHADOW
SIMULATION
LIVE
```

## Server contracts

Create typed contracts for:

- candidate;
- symbol workspace;
- account eligibility;
- session draft;
- authorization envelope;
- order intent;
- child account order;
- position state;
- resilience/resistance snapshot;
- journal event;
- parity result.

## Flags

```text
active_trader_next_visible
active_trader_next_read_only
active_trader_session_builder_enabled
active_trader_simulation_enabled
active_trader_live_canary_enabled
active_trader_multi_account_enabled
active_trader_runner_enabled
active_trader_overnight_conversion_enabled
```

All default false except read-only visibility in development.

## Tests

- migrations forward/back;
- immutable authorized draft;
- optimistic versioning;
- account allocation sums;
- authorization hash;
- environment constraints;
- no LIVE child intent without authorization;
- no browser-supplied eligibility.

---

# STAGE 2 — `/API/V3/ACTIVE-TRADER` READ PLANE

## Goal

Build additive read APIs over existing facts and Moomoo feature contracts.

## Endpoints

```text
GET /api/v3/active-trader/session
GET /api/v3/active-trader/candidates
GET /api/v3/active-trader/symbol/:symbol
GET /api/v3/active-trader/accounts
GET /api/v3/active-trader/orders
GET /api/v3/active-trader/positions
GET /api/v3/active-trader/journal
GET /api/v3/active-trader/parity
```

## Requirements

- canonical timestamps;
- field-level source and freshness;
- float source and confidence;
- current volume, dollar volume, RVOL and percentage of float;
- price structure;
- Moomoo data-quality placeholders;
- account eligibility returned server-side;
- no fabricated fields;
- explicit `UNAVAILABLE`.

## Tests

- API schema;
- source provenance;
- freshness;
- list/detail parity;
- no secret leakage;
- no write code reachable.

---

# STAGE 3 — MOOMOO DATA GATEWAY AND RATE GOVERNOR

## Goal

Implement data-only Moomoo collection and deterministic provider-rate governance.

## Services

```text
moomoo-opend.service
moomoo-gateway.service
moomoo-subscription-manager.service
moomoo-feature-engine.service
moomoo-replay-writer.service
moomoo-health-monitor.service
```

## Requirements

- one subscription owner;
- no live trade adapter;
- localhost/network isolation;
- Bitwarden tmpfs rendering;
- quote, K_1M, order book and ticker subscriptions;
- sequence and reconnect epochs;
- provider and receive timestamps;
- entitlement and quota truth;
- append-only WAL and Parquet replay;
- compact PostgreSQL feature snapshots;
- account-level place/modify token-bucket library;
- emergency/protection reserve;
- do not implement the legacy 750 ms chase.

## Tests

- recorded callback replay;
- reconnect;
- first-push cached marker;
- sequence gap;
- stale data;
- quota exhaustion;
- L1/L2 profiles;
- token-bucket accounting;
- no request above documented limits.

---

# STAGE 4 — ACTIVE TRADER NEXT READ-ONLY UI

## Goal

Create a separate application and bundle at `/v3-next`.

## Structure

Prefer:

```text
apps/command-center-v3-next/
```

Do not rewrite `apps/command-center-v3`.

Reuse only stable, additive shared types or components.

## UI

Implement:

- classic/next switch;
- session strip;
- prime queue;
- symbol workspace;
- chart;
- Level 2 ladder;
- time and sales;
- account panel read-only;
- positions panel;
- journal panel;
- source/freshness indicators;
- build marker.

## Requirements

- no mutating controls enabled;
- separate bundle;
- `/v3` unchanged;
- responsive terminal layout;
- keyboard navigation;
- accessible status text;
- no UI-only trading state.

## Tests

- TypeScript;
- design guard;
- Playwright;
- `/v3` regression;
- `/v3-next` smoke;
- switch behavior;
- old/new data parity;
- stale and unavailable states.

---

# STAGE 5 — SESSION BUILDER, ACCOUNT CHECKBOXES, AND SAVE

## Goal

Implement the operator configuration workflow without 2FA or trading.

## Mutating endpoints

```text
POST /api/v3/active-trader/session/draft
POST /api/v3/active-trader/session/validate
```

## UI

Add:

- account checkboxes;
- shares/notional/risk-based sizing;
- per-account quantity;
- allocation modes;
- session bounds;
- risk budgets;
- runner policy;
- save;
- draft version history;
- validation errors.

## Rules

- browser sends intent only;
- server computes eligibility and quantity caps;
- save creates immutable draft version;
- edits create new versions;
- no authorization;
- no OpenD unlock;
- no order.

## Tests

- multi-account allocation;
- one account ineligible;
- over-buying-power;
- over-risk;
- duplicate save;
- stale account facts;
- concurrent edit;
- exact draft hash.

---

# STAGE 6 — SESSION 2FA AND AUTHORIZATION SERVICE

## Goal

Implement one-time session authorization without enabling order submission.

## Endpoints

```text
POST /api/v3/active-trader/session/2fa
POST /api/v3/active-trader/session/activate
POST /api/v3/active-trader/session/pause
POST /api/v3/active-trader/session/revoke
POST /api/v3/active-trader/session/kill
```

## Requirements

- reuse existing approved 2FA mechanism;
- bind exact draft hash;
- bind operator identity;
- bind account set, quantities, universe, risk and time limits;
- single-use authorization challenge;
- no authorization renewal from browser refresh;
- activation state server-side;
- revoke atomically;
- activation still cannot reach broker because live flag false;
- full audit.

## Tests

- valid 2FA;
- replayed 2FA;
- expired challenge;
- changed draft;
- duplicate activation;
- two browser tabs;
- pause/revoke;
- entry cutoff;
- session expiry;
- kill switch.

---

# STAGE 7 — SHADOW PRIME, FIRE, RESILIENCE, AND RESISTANCE

## Goal

Run the full decision engine with zero orders.

## Implement

- candidate state machine;
- prime/fire policy;
- multi-level OFI;
- queue imbalance;
- microprice;
- replenishment/cancel features;
- tape aggression;
- resilience score;
- resistance score;
- runner state machine;
- hard/soft exit decisions;
- event-sourced journal;
- replay references.

## Requirements

- book-only events cannot act without persistence and tape;
- deterministic code only;
- feature versions;
- no lookahead;
- no LLM in event path;
- Sentinel/agent review may evaluate after the fact only.

## Acceptance

- at least 60 shadow fires before promotion;
- scored false positives;
- complete journal;
- replay reconstruction;
- no orders.

---

# STAGE 8 — SIMULATION EXECUTION

## Goal

Exercise the exact session and order code against simulation.

## Implement

- simulation child orders;
- bounded entry limit manager;
- account-level rate governor;
- partial fills;
- simulated broker-native protection;
- scale-outs;
- runner transitions;
- automatic exits;
- reconciliation;
- restart recovery.

## Requirements

- no live environment;
- same authorization contracts;
- same order-intent schema;
- same journal;
- deterministic fault injection.

## Acceptance

- two weeks or architecture-defined simulation window;
- no rate-limit violations;
- no duplicate order;
- no unprotected simulated fill;
- restart recovery;
- fill/slippage report;
- resilience/resistance outcome report.

---

# STAGE 9 — JOURNAL, DARWIN, AND LEARNING INTEGRATION

## Goal

Make every decision reviewable and scoreable.

## Implement

- Active Trader journal timeline;
- replay scrubber;
- execution-quality integration;
- MFE/MAE;
- capture ratio;
- exit efficiency;
- runner outcome;
- counterfactual windows;
- Darwin scoring;
- nightly reflection inputs;
- Iris lesson candidate;
- Hermes hypothesis candidate.

## Requirements

- agents do not alter live thresholds;
- no self-scoring;
- no secret or raw credential in journal;
- replay retention and manifest validation.

## Acceptance

- 100% required journal events;
- outcome scoring;
- one full case → lesson candidate → hypothesis candidate loop;
- no production config mutation.

---

# STAGE 10 — CONTROLLED LIVE CANARY

## Goal

Activate the architecture-owner-approved smallest live canary.

This stage requires a fresh explicit operator instruction at execution time even though the architecture phase is approved.

## Preconditions

- all prior stages pass;
- live adapter implemented and capability-probed;
- Moomoo data entitlement verified;
- broker-native or independently survivable protection verified;
- account eligibility and current intraday-margin policy verified from broker;
- positive shadow and simulation evidence;
- OpenD trade unlock isolated to one gateway;
- account-level rate governor tested;
- UPS/network/clock monitoring;
- old/new parity;
- kill switch and rollback;
- live flag still false until final activation.

## Canary envelope

Return for operator review:

```text
account:
symbols/universe:
max trades:
max concurrent:
max gross notional:
max per trade:
max risk per trade:
max daily loss:
entry window:
expiry:
runner policy:
overnight conversion:
place/modify budgets:
protection:
rollback:
```

## Activation

1. save exact session;
2. show hash;
3. one session 2FA;
4. enable the bounded live session;
5. automated orders only within envelope;
6. real-time audit;
7. entry cutoff;
8. manage open positions to flat;
9. lock OpenD;
10. reconcile and close out.

## Live closeout

```text
SESSION AUTHORIZATION ID:
SESSION HASH:
ORDERS:
FILLS:
MODIFICATIONS:
RATE LIMIT VIOLATIONS: 0
UNAUTHORIZED ORDERS: 0
UNPROTECTED FILLS: 0
DUPLICATE ORDERS: 0
POSITIONS FLAT:
BROKER/DB PARITY:
JOURNAL COMPLETE:
SESSION CLOSED:
OPEND LOCKED:
```

Stop immediately on any invariant failure.

---

# STAGE 11 — DUAL OPERATION AND PRIMARY-SURFACE DECISION

## Goal

Operate `/v3` and `/v3-next` in parallel long enough to decide whether the new surface becomes primary.

## Requirements

- daily parity report;
- incident count;
- operator usability findings;
- latency;
- build/deployment rollback;
- no legacy retirement during observation.

## Exit decision

```text
KEEP DUAL
PROMOTE /V3-NEXT
RETOOL
ROLL BACK
```

Retiring `/v3` requires a separate architecture-owner decision.

---

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
```
