| Sequence-gap detection | every detected gap recorded |
| Agent artifacts scored | >=95% |
| KB retrieval provenance | 100% |
| Live orders without authorization | 0 |

## 20.2 Fail-open and fail-closed

Fail open for display only:

- research card after deterministic pass;
- Sentinel reflective review unavailable;
- non-critical explanation service unavailable.

Fail closed:

- proposal eligibility;
- stale required input;
- validation hash mismatch;
- account uncertainty;
- adapter uncertainty;
- missing 2FA;
- Moomoo sequence or entitlement uncertainty for a strategy that requires L2;
- missing broker-native protection for live scalp.

## 20.3 No silent degradation

Every fallback is visible:

```text
L2 unavailable — L1 profile active
Sentinel unavailable — deterministic research only
OAuth lane unavailable — single lane
Moomoo stale — microstructure excluded
legacy packet — rebuild required
review timeout — proposal blocked
```

---

# 21. SECURITY AND THREAT MODEL

## 21.1 Threats

- prompt injection from news, documents, tool output, or chat;
- memory poisoning;
- malicious skill or MCP tool;
- model-route confusion;
- cloud fallback masquerading as local;
- secret exfiltration;
- stale or replayed authorization;
- agent intent drift;
- correlated model consensus;
- dependency supply-chain compromise;
- OpenD session hijack;
- replay-data tampering;
- order duplication;
- cross-environment credential leakage.

## 21.2 Controls

- allowlisted tools;
- typed schemas;
- content classification;
- secret redaction before model context;
- immutable hashes;
- capability tokens;
- environment separation;
- package hashes and provenance;
- model-route recording;
- single-use authorization;
- idempotency;
- read-only shadow roles;
- staging-only writes;
- lesson ratification;
- signed or checksummed replay manifests;
- no model-generated shell in production;
- no candidate package on production PATH before promotion.

## 21.3 Supply-chain controls

For every candidate package:

```text
package source
version
hash
signature/attestation where available
dependency lock
SBOM
license
known vulnerabilities
test artifact
promotion approval
```

---

# 22. UNIFIED IMPLEMENTATION SPINE

This replaces separate A-, K-, and M-phase numbering.

## P0 — Baseline and containment

Deliver:

1. `SYSTEM_RUNTIME_BASELINE_<DATE>.md`
2. `MODEL_VERSION_COMPATIBILITY_MATRIX_<DATE>.md`
3. `AGENT_TOOL_PERMISSION_MATRIX_<DATE>.md`
4. `KNOWLEDGE_CORPUS_EMBEDDING_AUDIT_<DATE>.md`
5. `MOOMOO_ENTITLEMENT_QUOTA_LATENCY_AUDIT_<DATE>.md`
6. `WATCH_DECISION_INTEGRITY_POPULATION_AUDIT_<DATE>.md`
7. `AGENT_SCORECARD_BASELINE_<DATE>.md`
8. `RUNTIME_UPGRADE_ROLLBACK_PLAN_<DATE>.md`

Also finish the Watch universal-gate acceptance matrix.

Exit gate:

```text
no current mechanics without verified ticket
scheduler state honest
population migrated or visibly unverified
```

## P1 — Upgrade laboratory

- create prod/shadow/lab identities;
- create candidate directories and service templates;
- create lab DB role/schema;
- create test Bitwarden collection;
- implement runtime candidate registry;
- build OpenAI, Hermes and OpenClaw candidate instances;
- no production cutover.

Exit gate:

```text
candidate isolation proven
production channels unreachable from lab
production broker secrets absent
atomic rollback tested
```

## P2 — Minimum Viable Loop schema

- MVL tables;
- KB API;
- initial seed extraction;
- Sentinel run artifacts;
- Darwin score contract;
- nightly reflection job.

Exit gate:

```text
one end-to-end known-bad Watch case
retrieval
review
quarantine
case
score
candidate lesson
```

## P3 — Sentinel and Argus production shadow

- Sentinel kernel on every Watch ticket;
- reflective review in shadow;
- Argus population scans;
- measure SLA and false positives;
- no proposal-policy dependency yet except deterministic gate.

Exit gate:

```text
100 artifacts
20 regression fixtures
measured false-positive rate
no page wedging
```

## P4 — MVL release policy

- research fail-open labeling;
- proposal fail-closed timeout;
- model-policy routing;
- local-only proof;
- OAuth hash binding;
- premium estimate and confirmation.

Exit gate:

```text
release classes proven
no model override of deterministic failure
```

## P5 — Moomoo data foundation

- entitlement and quota audit;
- OpenD data-only isolated service;
- gateway owner;
- subscription manager;
- sequence and timestamp controls;
- append-only replay;
- no decision consumption.

Exit gate:

```text
5 full RTH sessions captured
reconnect recovery proven
sequence gaps visible
quota accounting exact
```

## P6 — Moomoo deterministic features and Pulse shadow

- feature engine;
- feature snapshots;
- replay determinism;
- L1/L2 profile distinction;
- Pulse shadow artifacts;
- Watch display as non-authoritative evidence.

Exit gate:

```text
20 RTH sessions
feature parity replay/live
Pulse scored
no tick-path LLM
```

## P7 — Broker capability, rejection, and notification fabric

- discover all API-enabled Alpaca, Moomoo, and Schwab accounts;
- capability registry;
- normalized rejection classifier;
- primary/fallback account policy;
- notification projection;
- no broker writes except mocks/replay.

Exit gate:

```text
all accounts inventoried
unsupported capabilities explicit
Schwab broker-assisted rejection fixture
fallback duplicate-fill protection proven
```

## P8 — Active Trader Next read-only workspace

- create separate `/v3-next` Vite app and bundle;
- add classic/next navigation;
- implement session strip, prime queue, symbol workspace, account panel, position panel, and journal panel;
- use additive `/api/v3/active-trader` read endpoints;
- WebSocket market/session projection;
- no session mutation;
- no orders.

Exit gate:

```text
old/new quote parity
candidate parity
data freshness visible
no old-route regression
switch and rollback verified
```

## P9 — Session builder, feature modal, and shadow scalp

- saveable session drafts;
- account checkboxes and per-account quantities;
- server-side allocation and risk validation;
- authorization-envelope preview;
- shadow-only prime/fire/entry/management engine;
- resilience and resistance scores;
- event-sourced journal;
- zero orders.

Exit gate:

```text
>=60 scored fires
account-allocation validation
resilience/resistance replay
no lookahead
zero broker writes
```

## P10 — Simulation multi-broker execution and Active Trader management

- one-time session 2FA against simulation policy;
- simulation order intents;
- centralized place/modify rate governor;
- bounded smart-limit entry;
- partial fills;
- simulated broker-native protection;
- scale-outs;
- runner transitions;
- exits;
- restart/reconciliation tests;
- dual dashboard parity.

Exit gate:

```text
>=2 weeks simulation
rate limits never exceeded
idempotency proven
protection confirmation proven
restart recovery proven
journal complete
```

## P11 — Journal, overnight controller, Drive, email, and credential scaffolding

- full event journal and replay;
- stage checkpoint controller;
- GitHub per-stage commits/push;
- Google Drive stage/final sync;
- Gmail completion/failure email;
- Bitwarden lab placeholders and operator TODO;
- read-only architect litmus review.

Exit gate:

```text
resume after interruption
Drive/GitHub hash parity
completion email delivered
operator TODO complete
reviewer made no writes
```

## P12 — Durable runtime expansion

Only after MVL evidence:

- Atlas;
- generalized checkpoints;
- handoffs;
- multi-agent budgets;
- run cancellation UI;
- specialist-agent activation.

Exit gate:

```text
MVL utility justifies runtime generalization
```

## P13 — Hermes hypothesis flywheel

- preregistration;
- deterministic evaluation;
- Darwin score;
- adjudication UI;
- config/code proposal;
- rollback observation.

Exit gate:

```text
first hypothesis completes full loop without direct mutation
```

## P14 — Approved Active Trader multi-broker live canary

The architecture owner approves implementation and activation of the smallest live Moomoo momentum-scalp canary through Active Trader Next after the readiness gate passes.

Required prerequisites:

- production-ready Moomoo live adapter;
- operator-present trade-unlock ceremony where required by Moomoo;
- one-time session-scoped 2FA implementation;
- signed and immutable session authorization envelope;
- server-side session-policy enforcement on every order;
- broker-native or equivalent independently survivable protection;
- current account and PDT/day-trade review;
- UPS, network monitoring, clock health, and reconnect recovery;
- positive shadow evidence;
- positive simulation evidence;
- fill and slippage model review;
- adapter idempotency;
- order and position reconciliation;
- hard daily loss, notional, trade-count, concurrent-position, and chase limits;
- operator-visible session draft, account allocations, live-arm and kill switch;
- old/new dashboard parity and rollback;
