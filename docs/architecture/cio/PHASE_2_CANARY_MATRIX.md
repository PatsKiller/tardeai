# Phase 2 Canary Matrix

**Date:** 2026-08-08  
**Status:** FINAL

## Legend
- PASS: Verified with deterministic/structural tests
- BUILT_READY: Implementation complete, requires live activation
- N/A: Not applicable to current phase

## Canary Matrix

| # | Canary ID | Category | Description | Status |
|---|-----------|----------|-------------|--------|
| 1 | P2-RUN-001 | Run Lifecycle | Run creation from wake | PASS |
| 2 | P2-RUN-002 | Run Lifecycle | Run lifecycle transitions | PASS |
| 3 | P2-RUN-003 | Run Lifecycle | Health block stops synthesis | PASS |
| 4 | P2-RUN-004 | Run Lifecycle | Degraded health allows run | PASS |
| 5 | P2-RUN-005 | Run Lifecycle | Snapshot ID binding | PASS |
| 6 | P2-RUN-006 | Run Lifecycle | Profile version binding | PASS |
| 7 | P2-RUN-007 | Run Lifecycle | IPS version binding | PASS |
| 8 | P2-RUN-008 | Run Lifecycle | Crash recovery | PASS |
| 9 | P2-RUN-009 | Run Lifecycle | Budget enforcement | PASS |
| 10 | P2-RUN-010 | Run Lifecycle | Call limit enforcement | PASS |
| 11 | P2-RUN-011 | Run Lifecycle | No duplicate run from duplicate wake | PASS |
| 12 | P2-RUN-012 | Run Lifecycle | Zero-cost no-work run | PASS |
| 13 | P2-SNAP-001 | Snapshot | Domain AVAILABLE collection | PASS |
| 14 | P2-SNAP-002 | Snapshot | Domain STALE detection | PASS |
| 15 | P2-SNAP-003 | Snapshot | DATA_UNAVAILABLE typing | PASS |
| 16 | P2-SNAP-004 | Snapshot | No fabrication of missing data | PASS |
| 17 | P2-SNAP-005 | Snapshot | Hash determinism | PASS |
| 18 | P2-SNAP-006 | Snapshot | Sealed immutability | PASS |
| 19 | P2-SNAP-007 | Snapshot | Invalid domain rejection | PASS |
| 20 | P2-SNAP-008 | Snapshot | Invalid state rejection | PASS |
| 21 | P2-SNAP-009 | Snapshot | Evidence record format | PASS |
| 22 | P2-SNAP-010 | Snapshot | Canonical snapshot builder | PASS |
| 23 | P2-SPEC-001 | Specialists | Specialist routing by domain | PASS |
| 24 | P2-SPEC-002 | Specialists | Handoff to Maria | PASS |
| 25 | P2-SPEC-003 | Specialists | Handoff to Guardian | PASS |
| 26 | P2-SPEC-004 | Specialists | Handoff to Steph | PASS |
| 27 | P2-HERMES-001 | Hermes | High materiality triggers challenge | PASS |
| 28 | P2-HERMES-002 | Hermes | Non-material skips challenge | PASS |
| 29 | P2-HERMES-003 | Hermes | Challenge ID recorded in run | PASS |
| 30 | P2-COMMS-001 | Communication | Notification from action | PASS |
| 31 | P2-COMMS-002 | Communication | Material recommendation format | PASS |
| 32 | P2-COMMS-003 | Communication | Dedupe suppression | PASS |
| 33 | P2-COMMS-004 | Communication | Expiry before delivery | PASS |
| 34 | P2-COMMS-005 | Communication | Shadow mode no live Telegram | PASS |
| 35 | P2-COMMS-006 | Communication | No execution from communication | PASS |
| 36 | P2-BUDGET-001 | Budget | All budgets within $0.25 cap | PASS |
| 37 | P2-BUDGET-002 | Budget | Budget-deferred not fallback | PASS |
| 38 | P2-BUDGET-003 | Budget | Cost tracking per run | PASS |
| 39 | P2-BUDGET-004 | Budget | Run explainability | PASS |
| 40 | P2-BUDGET-005 | Budget | Quality grounding check | PASS |
| 41 | P2-REC-001 | Recovery | Event store survives restart | PASS |
| 42 | P2-REC-002 | Recovery | No duplicate wake after replay | PASS |
| 43 | P2-REC-003 | Recovery | Handoff persistence | PASS |
| 44 | P2-REC-004 | Recovery | Notification persistence | PASS |
| 45 | P2-REC-005 | Recovery | Fresh session reconstruction | PASS |
| 46 | P2-PROD-001 | Production | One owner per schedule | PASS |
| 47 | P2-PROD-002 | Production | No duplicate schedules | PASS |
| 48 | P2-PROD-003 | Production | No OpenClaw cron | PASS |
| 49 | P2-PROD-004 | Production | No financial heartbeat | PASS |
| 50 | P2-PROD-005 | Production | No specialist independent cron | PASS |
| 51 | P2-PROD-006 | Production | Alex advisory only | PASS |
| 52 | P2-PROD-007 | Production | PRO MAX requires confirmation | PASS |
| 53 | P2-PROD-008 | Production | Containment preserved | PASS |
| 54 | P2-LEARN-001 | Learning | Candidate lesson created | PASS |
| 55 | P2-LEARN-002 | Learning | Cannot self-modify policy | PASS |
| 56 | P2-LEARN-003 | Learning | Only allowed effects | PASS |
| 57 | P2-LEARN-004 | Learning | No execution from learning | PASS |

## Canaries Requiring Live Activation

| # | Canary ID | Category | Description | Status |
|---|-----------|----------|-------------|--------|
| 58 | P2-RUN-LIVE-001 | Live Run | Real governed synthesis call | BUILT_READY |
| 59 | P2-RUN-LIVE-002 | Live Run | Real specialist handoff | BUILT_READY |
| 60 | P2-RUN-LIVE-003 | Live Run | Real Hermes challenge | BUILT_READY |
| 61 | P2-RUN-LIVE-004 | Live Run | Real provider cost tracking | BUILT_READY |
| 62 | P2-SPEC-LIVE-001 | Live Spec | Specialist artifact delivery | BUILT_READY |
| 63 | P2-SPEC-LIVE-002 | Live Spec | Specialist handoff completion | BUILT_READY |
| 64 | P2-HERMES-LIVE-001 | Live Hermes | Hermes challenge resolution | BUILT_READY |
| 65 | P2-HERMES-LIVE-002 | Live Hermes | Hermes disagreement preserved | BUILT_READY |
| 66 | P2-COMMS-LIVE-001 | Live Comms | Real Telegram delivery | BUILT_READY |
| 67 | P2-COMMS-LIVE-002 | Live Comms | Real Telegram receipt | BUILT_READY |
| 68 | P2-REC-LIVE-001 | Live Recovery | Gateway restart | BUILT_READY |
| 69 | P2-REC-LIVE-002 | Live Recovery | Host restart | BUILT_READY |

**Summary:** 57 deterministic/structural PASS + 12 BUILT_READY = 69 total canaries defined.
