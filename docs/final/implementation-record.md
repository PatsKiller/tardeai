# Communications Gateway — Implementation Record (Phases 0–11)

**Status:** Communications Gateway program documentation (Phases 0–11).
**Date:** 2026-09-05

**As of:** 2026-09-07 (re-attest `docs/audit/live-attest-2026-09-05.md`, served `3cb740e4c69380fe9355da6b4857a94cf21e6c27` = PR #874 Wave E + docs; earlier `f88853e89` = PR #873 poller rewiring)  
**Production activation:** **CANARY for Telegram `ops` only** (`COMMS_GATEWAY_MODE=CANARY`, `CANARY_CLASSES=ops`, `CANARY_CHATS=6993102664,8797974247`). A short-lived **ACTIVE for `ops`** posture (`COMMS_GATEWAY_ACTIVE_CLASSES=ops`, ~40 min soak) was **reverted to CANARY** — see `docs/deployment/production-activation.md` and `docs/deployment/canary-results.md`. Default remains **OFF** for every other class and channel.  
**Worktree:** `wt/comms-gateway-phase0` (`tradeai-wt-comms-gateway-phase0`)

Classification: **designed** · **built** (code+tests in tree, often BUILT_DARK) · **tested** · **activated** · **deferred**

---

## Summary table

| Phase | Title | Designed | Built | Tested | Activated (prod) | Deferred / notes |
|---|---|---|---|---|---|---|
| 0 | Truth audit + sign-off | yes | audit packet | attestation tooling | sign-off ACCEPTED (planning) | continuous re-attest |
| 1 | CommunicationEvent@v2 ledger | yes | yes | yes | **no** (OFF) | producer adoption |
| 2 | Gateway enforcement ratchets | yes | static + runtime helpers | yes | ratchets LIVE; ownership **no** | Telegram zero = Phase 9 |
| 3 | ChannelDelivery@v1 ledger | yes | yes (SHADOW stubs) | yes | **no** | provider settlement ownership |
| 4 | Subject memory | yes | yes | yes | **no** | broader CC wiring |
| 5 | Controlled curation receipts | yes | yes (no live LLM) | yes | **no** | producer use |
| 6 | Librarian retention | yes | yes (dry_run expiry) | yes | **no** | prod schedule |
| 7 | `/v3/communications` workspace | yes | yes (BUILT_DARK) | portal tests | **yes (LIVE, HTTP 200)** | live CURRENT attest |
| 8 | Agent consumption contracts | yes | yes | yes | **no** | subscribe real agents |
| 9 | Migrate Telegram senders / zero bypass | yes | yes (high-risk cohort) | ratchet + migration note | **partial (ops CANARY)** | remaining bypass cohort / empty baseline |
| 10 | Channel adapters (email/Slack/WhatsApp) | yes | yes (`channel_adapters.py`, deliver=False default) | yes | **no** | real deliver only CANARY/ACTIVE later |
| 11 | Rollout/rollback docs + SHADOW compare | yes | docs + `shadow_compare.py` | unit tests | **ops CANARY** | canary/ACTIVE evidence recorded |

---

## Built modules (`scripts/lib/comms/`)

| Module | Phase | Role |
|---|---|---|
| `mode.py` | 1 | `OFF`/`SHADOW`/`CANARY`/`ACTIVE`; default OFF |
| `identity.py` | 1 | `event_id`, idempotency / content hashes |
| `event.py` | 1 | `CommunicationEvent@v2` |
| `client.py` | 1 | `publish_communication` (no provider I/O) |
| `adapters.py` | 1 | Alert/plain → event constructors (no send) |
| `enforcement.py` | 2 | `require_event_id`, ownership asserts |
| `delivery.py` | 3 | `ChannelDelivery@v1` reserve/settle/chunks |
| `subject_memory.py` | 4 | SubjectThread attach/retrieve |
| `curation.py` | 5 | CurationReceipt; deterministic + LLM apply w/ fallback |
| `librarian.py` | 6 | RetentionDecision; dry-run expiry; knowledge candidates |
| `agent_contracts.py` | 8 | Subscriptions + AgentConsumptionReceipt |
| `channel_adapters.py` | 10 | email/slack/whatsapp via gateway; default deliver=False |
| `shadow_compare.py` | 11 | Legacy vs gateway compare + memory observations |
| `__init__.py` | — | Public exports |

### Migrations (built, apply separately)

- `migrations/2026_09_05_communication_event_ledger.sql`  
- `migrations/2026_09_05_communication_delivery_ledger.sql`  
- `migrations/2026_09_05_communication_subject_memory.sql`  
- `migrations/2026_09_05_communication_librarian.sql`  
- `migrations/2026_09_05_communication_agent_consumption.sql`

### Tests (built)

- `tests/test_comms_communication_event.py`  
- `tests/test_comms_enforcement_gate.py`  
- `tests/test_comms_delivery_ledger.py`  
- `tests/test_comms_subject_memory.py`  
- `tests/test_comms_curation.py`  
- `tests/test_comms_librarian.py`  
- `tests/test_comms_agent_contracts.py`  
- `tests/test_comms_channel_adapters.py`  
- `tests/test_comms_shadow_compare.py`  
- `tests/test_communications_portal.py`

### Docs tree

- Audit: `docs/audit/*` (Phase 0)  
- Architecture: `docs/architecture/communication-event.md`, `delivery-ledger.md`, `subject-memory.md`, `curation-and-provenance.md`, `retention.md`, `gateway-enforcement.md`, `communications-workspace.md`, `agent-contracts.md`  
- Testing: `docs/testing/test-plan.md`, `docs/testing/unit-results.md`  
- Deployment: `docs/deployment/rollout-plan.md`, `rollback-plan.md`, `canary-results.md`, `production-activation.md`  
- Final: this file

---

## Activated in production

**Telegram `ops` only, CANARY.** `COMMS_GATEWAY_MODE=CANARY` with
`COMMS_GATEWAY_CANARY_CLASSES=ops` and `COMMS_GATEWAY_CANARY_CHATS=6993102664,8797974247`
(via systemd `32-comms-gateway-mode.conf`). Owned `ops` deliveries settle `SENT` with
`provider_message_id`; non-owned classes settle `LEGACY_DELIVERED` (F1 fixed). Every other
class stays legacy-send + best-effort ledger. Repo default remains OFF.

**Mode history (2026-09-05):** CANARY (2 sample sends) → **ACTIVE** `ops` (operator soak,
~40 min, later judged premature) → **reverted to CANARY** with the chat filter above. The
ACTIVE posture is documented for the record; it is **not** the current live mode. See
`docs/deployment/production-activation.md`, `docs/deployment/canary-results.md`, and the
live re-attestation in `docs/audit/live-attest-2026-09-05.md`.

**Poller rewiring (Wave C) merged.** `run_telegram_callback_poller.py` now uses
`claim_update` / `commit_checkpoint` / `build_inbound_event` / `quarantine_callback` from
`scripts/lib/comms/inbound.py` (PR #873, `f88853e89`) — the offset-before-processing defect
(F-documented in `docs/audit/wave-c-inbound-implementation.md`) is closed on the served
path. The inbound checkpoint + quarantine migrations are applied to prod DB.

---

## Deferred (explicit)

1. **Telegram class widening** — `ops` is ACTIVE; `operator_alert` / `health` / `research` /
   `digest` / `protection_incident` still legacy (canary ladder pending — Wave B).
2. **Phase 10 activation** — Adapters built with `deliver=False` default; CANARY/ACTIVE deliver still gated.
3. **Inbound completeness** — **DONE.** `operator_command` rows exist; durable update_id checkpoint + callback quarantine built and the poller rewired (Wave C, PR #873 `f88853e89`). Sibling pollers (`telegram_reply_processor.py`, `cio_telegram_bot.py`) remain on the old offset handling — a named, deferred gap.
4. Live LLM curation wiring; scheduled librarian expiry on prod; full agent subscription wiring (Waves D/E/F).

---

## Phase 11 deliverable statement

Phase 11 adds controlled-activation **documentation** and a **SHADOW comparison helper** so ACTIVE can be justified later with evidence. It does **not** change production mode, does **not** migrate Telegram senders, and does **not** implement Phase 10 channel adapters.