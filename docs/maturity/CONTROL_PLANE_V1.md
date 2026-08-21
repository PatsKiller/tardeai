# Maturity Control Plane v1 — architecture map

READ_ONLY_ADVISORY. AUTO-PROMOTION TO TRADING: DISABLED.

## Existing surfaces (8d18a668)

`8d18a668` (#350, 2026-08-17) is an **ancestor snapshot**, not CURRENT. Live serve as of 2026-08-21 evening: `fe34482b` (#433). Maturation slices G.1/I.0/A.1/B.1: PRs #434 / #435.

| Surface | Path | Notes |
|---|---|---|
| Agents hub | `/v3/agents` | `AgentRuntimeHub` Runtime + Legacy analytics |
| CIO hub | `/v3/cio` | `CioHub` NOW / capital / posture / opportunities / report / evidence |
| Health hub | `/v3/health` | `HealthHub` + existing Ops autonomy tab |
| Agent-runtime read API | `/api/v3/agent-runtime/*` | GET-only, mutation=false |
| Phase 10 gate | `scripts/operator_packets/packet_e_promotion_gate.py` | intent files only; Phase 11 refused |
| Lessons | `scripts/lib/advisory/kb_lessons.py` | candidate/ratified/retired jsonl |
| Notification gate | `scripts/lib/cio_notification_signal.py` | IMMEDIATE/DIGEST/CC_ONLY/SUPPRESSED |

## Inserted

| Layer | Files |
|---|---|
| Schema / store | `scripts/lib/maturity_control/*` |
| CLI | `scripts/maturity_promotion.py` |
| GET API | `/api/v3/maturity/*` via `api_v3_maturity.py` |
| Control API | POST `/api/v3/maturity-control/*` (env-gated, not dashboard) |
| CC tabs | Agents Learning/Memory/Promotion/Cases/Evidence; CIO Notification Gate / Telegram / Senses; Health Intelligence loop + Memory |
| Durable memory | GET `/api/v3/maturity/memory`; JSONL `data/cio/aif_memory.jsonl`; SHADOW only |
| Daily intelligence | GET `/api/v3/maturity/heartbeat`; Health → Daily Intelligence; SYSTEM Telegram heartbeat |
| Investment books | GET `/api/v3/cio/investment-product`; CIO → Investment Books; wired `CIORunWorker` synthesis |

Phase 11 may set lesson overlay `SHADOW_INFLUENCE` or agent overlay `OPERATIONAL_ADVISORY`. It never enables broker, orders, stops, 2FA, or risk policy.
