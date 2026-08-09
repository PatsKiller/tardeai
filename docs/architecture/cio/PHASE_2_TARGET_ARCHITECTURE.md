# Phase 2 Target Architecture — Trade AI CIO

**Date:** 2026-08-08
**Phase:** P2.0 Authority Freeze
**Status:** FROZEN
**Depends On:** Phase -1 Acceptance (all P-1 modules operational)

---

## 1. System Topology

```
┌─────────────────────────────────────────────────────────────┐
│                       TRADE AI                              │
│                 (Canonical Financial Truth)                  │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Data Broker  │  │ CIO Action   │  │ Notification     │  │
│  │ (holdings,   │  │ Ledger       │  │ Outbox           │  │
│  │  risk, tax,  │  │ (P-1.3)      │  │ (P-1.7)          │  │
│  │  portfolio)  │  └──────────────┘  └──────────────────┘  │
│  └──────────────┘                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Agent        │  │ Health       │  │ Wake/Event       │  │
│  │ Handoff Q    │  │ Boundary     │  │ Detector         │  │
│  │ (P-1.4)      │  │ (P-1.5)      │  │ (P-1.6)          │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Operator     │  │ Financial    │  │ Hermes Challenge │  │
│  │ Profile      │  │ Domain       │  │ Queue            │  │
│  │ (P2.1)       │  │ Capabilities │  │ (P-1.9)          │  │
│  └──────────────┘  │ (P2.2)       │  └──────────────────┘  │
│                    └──────────────┘                         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Model Governance / Process Registry / Cost Tracker    │  │
│  │ (P-1.2A/B, llm_process_registry.json)                │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                       │  governed model bridge only
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                       OPENCLAW                               │
│                 (Governed Agent Reasoning Loop)              │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Alex (CIO)   │  │ Maria (PA)   │  │ Steph (Wealth)   │  │
│  │ P2.3 CIO Run │  │              │  │                  │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │ Guardian     │  │ Ledger       │                        │
│  │ (Risk)       │  │ (Tax)        │                        │
│  └──────────────┘  └──────────────┘                        │
│                                                             │
│  Tools: tradeai-readonly ONLY through allowlisted Trade AI  │
│         deterministic service interfaces                     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                       HERMES                                 │
│                 (Independent Research Challenger)            │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Independent schedule, independent research DB,       │  │
│  │ independent challenge queue (P-1.9)                  │  │
│  │ NOT subordinate to Alex                              │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Ownership Boundaries

| Domain | Owner | Notes |
|--------|-------|-------|
| Financial truth (portfolio, risk, tax, allocation) | Trade AI | Canonical source |
| CIO actions / runs / handoffs / wake | Trade AI | Durable event stores |
| Notifications / delivery state | Trade AI | Outbox pattern |
| Model governance / process registry / cost | Trade AI | Fail-closed governance |
| Agent reasoning loop | OpenClaw | Governed bridge only |
| Operator relationship / conversation | OpenClaw | Alex identity |
| Independent research | Hermes | Not Alex-subordinate |
| Infrastructure / health remediation | Platform | NEVER Alex |

---

## 2. Data Flow

```
Deterministic Trade AI Evidence
        │
        ▼
OpenClaw Governed Reasoning (Alex)
  ├─ Read: canonical Trade AI financial state
  ├─ Read: Data Broker outputs
  ├─ Read: deterministic portfolio/risk/tax evidence
  ├─ Read: CIO actions / runs / handoffs / artifacts
  ├─ Read: health decisions / wake jobs
  ├─ Read: Hermes challenges / results
  ├─ Read: notification delivery state
  │
  ├─ Write (through deterministic services ONLY):
  │   ├─ CIO action create/update → CIOActionLedger
  │   ├─ Handoff enqueue → AgentHandoffQueue
  │   ├─ Hermes challenge request → HermesChallengeQueue
  │   ├─ Operator notification enqueue → NotificationOutbox
  │   ├─ CIO run/case state → CIORunStore (P2.3)
  │   └─ Learning candidate proposal (future)
  │
  ▼
Deterministic Service Writes (event-sourced, hash-chained)
        │
        ▼
Notification Outbox → Delivery Worker → Operator (Telegram)
```

**Critical rule:** LLMs explain, compare, challenge, and summarize. They NEVER become the numeric source of truth for financial calculations. Risk calculations, tax lots/wash-sale, retirement cash-flow, income/distributions, portfolio weights/drift, and performance/attribution are all computed by deterministic Trade AI services.

---

## 3. Scheduler Architecture

Trade AI owns ALL financial scheduling. No duplicate schedules. No LLM heartbeat.

```
Scheduled Work:
  Daily CIO briefing     → Trade AI schedule → CIOWakeJobStore → Alex (via dispatcher)
  Weekly CIO review      → Trade AI schedule → CIOWakeJobStore → Alex
  Action follow-up due   → CIOEventDetector  → CIOWakeJobStore → Alex

Event-Driven Work:
  Health block start/clear  → CIOHealthBoundary → CIOActionLedger → wake → Alex
  Specialist completion     → AgentHandoffQueue → CIOEventDetector → wake → Alex
  Hermes challenge resolved → HermesChallengeQueue → CIOEventDetector → wake → Alex
  Operator message ingress  → Maria classification → AgentHandoffQueue → wake → Alex
  Outbound notification     → NotificationOutbox → Delivery Worker → Telegram
```

**Cost:** Wake detector is deterministic. $0 if no work. Durable wake job created when work exists. No LLM polling loop.

**One Trigger, One Owner:** Each recurring/event workflow has exactly one trigger, one owner, one durable state, one consumer, one retry owner, and one delivery owner.

---

## 4. Model Boundary

```
OpenClaw Agent
  │
  ├─ Request: "synthesize portfolio review"
  │
  ▼
Governed Model Bridge (cio_governed_model_bridge.py)
  │
  ├─ Resolve: actor=alex → process=alex_cio_synthesis
  ├─ Validate: process exists in llm_process_registry.json
  ├─ Check: cost cap not exceeded (LLM_GLOBAL_DAILY_USD_CAP = $0.25)
  ├─ Reserve: run budget
  ├─ Execute: deepseek-v4-pro (PRO lane)
  ├─ Settle: log consumption with provenance
  │
  ▼
Response → Agent (with governance_pass, model_provenance)
```

**Fallback:** NONE for financial agents. Direct paid-model fallback (OpenAI, Anthropic) is PROHIBITED. If governed route fails → typed failure → agent reports error → no silent degradation.

**Financial agents requiring governed routing:** Alex, Maria, Steph, Guardian, Ledger.

---

## 5. State Ownership Map

| State Domain | Canonical Owner | Storage | Access Pattern |
|---|---|---|---|
| Portfolio / holdings | Trade AI | Data Broker | Read-only via API |
| Performance / attribution | Trade AI | Data Broker | Read-only via API |
| Risk evidence | Trade AI | Risk services | Read-only via API |
| Tax lots / cost basis | Trade AI | Tax services | Read-only via API |
| IPS / goals | Trade AI | cio_operator_profile.py (P2.1) | Read + deterministic write |
| Operator profile | Trade AI | cio_operator_profile.py (P2.1) | Read + deterministic write |
| CIO actions | Trade AI | cio_action_ledger.jsonl | Append-only event store |
| Agent handoffs | Trade AI | agent_handoff_queue.jsonl | Append-only event store |
| Health decisions | Trade AI | CIOHealthBoundary | Deterministic service |
| Wake jobs | Trade AI | CIOWakeJobStore | Deterministic service |
| Notifications | Trade AI | NotificationOutbox | Append-only event store |
| Hermes challenges | Trade AI (Hermes) | HermesChallengeQueue | Independent queue |
| CIO runs | Trade AI | cio_runs.jsonl (P2.3) | Append-only event store |
| Conversations / preferences | OpenClaw | OpenClaw state | Non-authoritative |

---

## 6. Fresh-Session Reconstruction Contract

Alex MUST reconstruct operator goals, constraints, and financial context from Trade AI authoritative state on every material CIO run. Specifically:

1. **Operator Profile**: Read from `cio_operator_profile.py` event store — never from OpenClaw MEMORY.md or cached context
2. **IPS / Goals**: Read from `cio_operator_profile.py` — OPERATOR_CONFIRMED facts only
3. **Portfolio State**: Read from Trade AI Data Broker — current snapshot
4. **Risk Evidence**: Read from deterministic Trade AI risk services
5. **Tax / Account Constraints**: Read from deterministic Trade AI data
6. **Health Status**: Read from CIOHealthBoundary before any advisory work

OpenClaw MEMORY.md, conversation history, and agent context are NON-AUTHORITATIVE for financial facts. They may inform conversational tone and operator preferences but must never substitute for canonical Trade AI state.

---

## 7. Autonomy Levels

| Level | Name | Description | Phase |
|-------|------|-------------|-------|
| A0 | Manual Only | Operator triggers, reviews everything | Baseline |
| A1 | Autonomous Read/Research | Reads, gathers evidence, synthesizes without operator | P2 |
| A2 | Autonomous Advisory Action | Creates CIO actions, schedules follow-ups | P2 |
| A3 | Autonomous Operator Notification | Enqueues notifications for operator review | P2 (ceiling) |
| A4 | Financial Execution | Trade execution, position mutation, broker orders | P3+ (gated) |

**Hard ceiling for Phase 2:** A3 maximum. A4 (financial execution) is DEFINED but UNREACHABLE — gated behind explicit Phase 3 authorization with operator confirmation, broker integration, and risk-limit validation.

---

## 8. Cross-Cutting Rules

### Safety Invariants
- NEVER grant broker order submission to Alex
- NEVER grant trade execution to Alex
- NEVER grant position mutation to Alex
- NEVER grant risk-limit mutation to Alex
- NEVER grant 2FA access to Alex
- NEVER grant credential/secret access to Alex
- NEVER grant bank/account movement to Alex
- NEVER grant tax filing to Alex
- NEVER grant legal/estate authority to Alex
- NEVER grant infrastructure remediation to Alex
- NEVER grant systemctl/sudo/crontab to Alex
- NEVER allow self-modifying production policy
- NEVER allow silent paid-model fallback
- NEVER allow automatic PRO_MAX elevation

### Deterministic-First Rule
Risk calculations, tax lots/wash-sale, retirement cash-flow, income/distributions, portfolio weights/drift, and performance/attribution → deterministic Trade AI services compute the numbers. LLMs explain, compare, challenge, and summarize. They NEVER become the numeric source of truth.

### Evidence Return Types
Missing or problematic evidence returns typed states:
- `DATA_UNAVAILABLE` — data source not available
- `MODEL_UNAVAILABLE` — computational model not available
- `STALE` — data exists but exceeds freshness threshold
- `CONFLICTED` — multiple sources disagree
- `NOT_SUPPORTED` — domain not implemented

---

## 9. Files Created / Updated in P2.0

| File | Purpose |
|------|---------|
| `docs/architecture/cio/PHASE_2_TARGET_ARCHITECTURE.md` | This document |
| `docs/architecture/cio/PHASE_2_AUTHORITY_MATRIX.md` | Machine-readable authority by tool |
| `docs/architecture/cio/PHASE_2_TRIGGER_OWNERSHIP.md` | Trigger/owner/state mapping |
| `docs/architecture/cio/PHASE_2_DATA_AUTHORITY.md` | Data domain ownership |
