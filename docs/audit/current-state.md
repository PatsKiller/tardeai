# Communications Gateway — Current State

**Attested SOURCE_COMMIT:** `17e30dcbb9a091f2fb9916f3c0d4ccabd5c5e72e`  
**Companion docs:** `runtime-attestation.md`, `sender-inventory.md`, `gap-analysis.md`  
**Verdict:** Telegram works. A mature, channel-neutral, universally traceable communications fabric does **not**.

---

## Executive summary

Trade AI today is a **partially centralized Telegram delivery system** with sophisticated CIO notification identity controls, a dormant operator-alert outbox schema, a non-zero chokepoint ratchet, and source-built but unproven multi-channel adapters. It is **not** yet one Communications Fabric.

| Claim | Status |
|---|---|
| Telegram send/receive operational | PROVEN (LIVE) |
| Selected routing / wrappers exist | PROVEN (LIVE BUT PARTIAL) |
| Partial outbox / reporting | PROVEN (LIVE BUT PARTIAL / BUILT_DARK for normalized ACTIVE) |
| CIO notification lineage architecture | PROVEN (LIVE / LIVE BUT PARTIAL dual-path) |
| URL normalization | PROVEN (LIVE) |
| Some Command Center visibility (Reports) | PROVEN (LIVE BUT PARTIAL) |
| Universal CommunicationEvent | NOT PROVEN (ABSENT) |
| Universal GUIDs / lineage / receipts | NOT PROVEN |
| Universal retention / Librarian | NOT PROVEN (Hermes librarian ≠ message librarian) |
| Universal agent consumption receipts | NOT PROVEN |
| `/v3/communications` workspace | NOT PROVEN (ABSENT) |
| Zero bypass / universal chokepoint | NOT PROVEN (45 bypass producers) |
| Email / Slack / WhatsApp production activation | NOT PROVEN |

---

## What exists (evidence-backed)

### Telegram plane

- **Outbound general:** `scripts/telegram_alert.py` → `scripts/telegram_transport.py`.
- **Outbound CIO:** `scripts/lib/cio_telegram_transport.py` (separate credentials).
- **Inbound:** command/callback handlers + poller; `tradeai-cio-telegram.service` running.
- **URL policy:** `scripts/notification_url_builder.py` publicizes FQDN `/v3` links.
- **CI ratchet:** `scripts/check_telegram_chokepoint.py` + `config/telegram_chokepoint_baseline.json`.

### Operator alert normalization (built, not owning delivery)

- Typed `AlertEvent` + `publish_event` in `scripts/alert_outbox.py`.
- Occurrence / incident / delivery schema present on this host (`migration_applied: true`).
- Runtime mode **OFF** → legacy router/sender owns delivery.
- Modes: OFF / SHADOW / ACTIVE via `scripts/alert_runtime_mode.py`.

### CIO notification stack (strongest identity foundation)

- `cio_notification_signal.py` four-identity gate wired into material scan.
- JSONL outbox + delivery worker (shadow/live); dual path vs scanner direct-send remains.
- Replay / acceptance docs under `docs/cio/CIO_NOTIFICATION_*`.

### Multi-channel source adapters

- `scripts/alerting.py`: SMTP email, Slack webhook, Twilio WhatsApp — flag-gated.
- CIO WhatsApp Cloud API modules exist, converse flag-off.
- **Not** mediated by a universal gateway; activation unproven this attestation.

### Command Center

- Reports hub / portal over partial stores (`notification_log`, `telegram_outbox`, `alert_events`).
- **No** `/v3/communications` route or module.

---

## What does not exist

- `CommunicationEvent@v1/v2` type, tables, or client.
- Universal delivery ledger across channels.
- Cross-channel subject memory (do not confuse with `cio_rehydrate` instrument cognition).
- Named protected-fact curation contract for all messages.
- Universal Librarian retention decisions for communications.
- AgentConsumptionReceipt for all persistent agents.
- Zero-bypass enforcement (ratchet ≠ zero).

---

## Dual stacks (do not conflate)

| Stack | Store | Mode today | Owns egress? |
|---|---|---|---|
| Legacy Telegram | direct / `send_telegram` / router | default path | **YES** |
| Operator alert outbox | Postgres `alert_*` | OFF | NO |
| CIO notify | JSONL + workers | partial live / dual-path | PARTIAL |
| Advisory broker | JSONL SHADOW | SHADOW | NO |

The Communications Gateway program must **absorb** these into one ledger, not add a fifth parallel bus.

---

## Risk statement

Historical and current scans agree: **dozens of direct Telegram API producers** remain. Until the baseline is empty and runtime egress is confined, any claim of “universal gateway enforcement” is false.

---

## Next gate

Phase 0 exit requires operator sign-off on this packet plus owner assignment for every `MIGRATE` sender. Only then may Phase 1 (`CommunicationEvent` schema, still OFF) begin.
