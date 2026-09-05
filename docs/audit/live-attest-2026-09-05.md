# Communications Gateway — Live Attestation (re-attest, post #862/#864/#868)

```
Status: ACTIVE
as_of: 2026-09-05T10:45:00-04:00
Measured at: served build faf8c05d9cfa149c2efd7cadfb05a5bd7b3644d1
```

Supersedes `docs/audit/runtime-attestation.md` (which cited `17e30dcbb` and predated
production ACTIVE). All values below were read live via HTTP from the served release or
from `origin/main` at `faf8c05d9`; nothing here is a `[DOC-CLAIM]` about runtime.

---

## 1. Served build identity `[VERIFIED]`

Command: `curl -s http://127.0.0.1:7777/v3/build-meta.json`

| Field | Value |
|---|---|
| `git_sha` / `source_sha` / `build_sha` | `faf8c05d9cfa149c2efd7cadfb05a5bd7b3644d1` |
| `ui_version` | `3.14+mto3leec` |
| `built_at` | `2026-09-05T08:05:30.324Z` |

`origin/main` = `faf8c05d9` (merge of #870). The gateway merge line #862 → #864 → #868
is in the ancestry; header fixes #869/#870 landed on top without touching comms code.

## 2. Gateway mode and ownership `[VERIFIED]`

Command: `curl -s http://127.0.0.1:7777/api/v2/communications/health`

```json
"mode": "ACTIVE",
"delivery_owned": true,
"owned_classes": ["ops"],
"banner": "Ledger-backed · gateway owns Telegram classes: ops",
"ledger": { "source": "db", "db_reachable": true, "events_source": "db",
            "deliveries_source": "db", "subjects_source": "db" }
```

Gateway owns **`ops` only**. Everything else is legacy-send + best-effort ledger.

## 3. Ledger population `[VERIFIED]`

Commands:
- `curl -s 'http://127.0.0.1:7777/api/v2/communications/events?limit=200'`
- `curl -s 'http://127.0.0.1:7777/api/v2/communications/deliveries?limit=200'`

| Store | Visible rows |
|---|---|
| `communication_events` | 55 |
| `channel_delivery` | 54 |
| `subject_thread` | present (subjects source = db) |

`/v3/communications` returns **HTTP 200** (route live).

## 4. Disposition matrix (spec vs live)

| Spec requirement | Live disposition |
|---|---|
| CommunicationEvent@v2 ledger | **LIVE** (DB, producer-adopted) |
| `event_id` before Telegram send, owned classes | **LIVE for `ops`** (`telegram_alert._send_via_comms_gateway`) |
| Zero static Telegram chokepoint bypasses | **LIVE** (baseline `files: []`) |
| Gateway owns all outbound Telegram | **PARTIAL** — `ops` only |
| `/v3/communications` workspace | **LIVE** (200) |
| Inbound command events | **PARTIAL** — `operator_command` rows present (`inbound_7d`); full update_id/checkpoint quarantine not re-attested |
| SubjectThread / subject memory | **LIVE but body-derived** (F2) |
| CurationReceipt + tiered LLM | **BUILT_DARK** (no live LLM) |
| MessageArtifact@v1 | **ABSENT** |
| Librarian retention scheduled + purge receipts | **BUILT_DARK** (dry-run only) |
| AgentConsumptionReceipt wired | **BUILT_DARK** |
| Email/Slack/WhatsApp ACTIVE | **BUILT `deliver=False`** |

## 5. New findings (this attestation)

**F1 — non-owned deliveries stuck `RESERVED`, never settle.**
Of 54 deliveries, ~45 are `RESERVED` with `provider_message_id: null`, `sent_at: null`.
The best-effort ledger mints a `ChannelDelivery` stub on publish but the legacy path does
not settle it. Owned `ops` rows settle `SENT` with a provider id (`50581,50582`). A
`RESERVED` row with no settlement is indistinguishable from an in-flight send; the ledger
reads as a queue that never drains. Fix: settle the stub (SENT/legacy) for non-owned
classes, or mark them `LEGACY_DELIVERED`, so `RESERVED` means "actually in flight".

**F2 — `subject_key` is body-derived, not domain-aware.**
Live subjects are `telegram:operator_alert:⚠️ <b>Health Agent: DEGRADED — 68/100</b>…`
(raw body, truncated). Spec requires a deterministic domain-aware key (symbol / incident /
proposal / system component). Body-derived keys fragment the thread on any wording change
and defeat same-subject retrieval.

**F3 — `message_class` taxonomy is inconsistent.**
Classes observed: `ops`, `ops_alert`, `operator_alert`, `operator_command`, `health`,
`health_digest`, `health_debug`, `research`, `digest`. `owned_classes=["ops"]` therefore
catches only a sliver; `health`/`operator_alert` events are not owned even when they are
operational alerts. Needs a single class vocabulary before canary widening.

**F4 — test-suite leakage residue in prod DB.**
A delivery carries `provider_message_id: "wamid.test_1"`. Fixed by
`edcf137f8` and `c2986912b` ("stop the suites writing to the production database"); the
row is residue, not ongoing.

**F5 — `retention_class` drift.**
Observed `operational`, `operational_30d`, `ops_7d`, `inbound_7d`, and bare `none`. Not
yet mapped to the proposed retention policy; Librarian is dry-run only.

## 6. What changed since the `17e30dcbb` attestation

- `17e30dcbb` → `faf8c05d9`: gateway Phases 0–11 (#862), CANARY/ACTIVE (#864),
  delivery_owned honesty + `provider_message_id` (#868), comms test prod-write closures
  (`edcf137f8`, `c2986912b`), then header fixes (#869/#870).
- CommunicationEvent moved **ABSENT → LIVE**; chokepoint baseline **non-empty → empty**;
  `/v3/communications` **absent → 200**; delivery ownership **legacy → `ops`**.

## 7. Remaining gaps (fed into the wave plan)

Wave B (canary ladder) · Wave C (inbound completeness) · Wave D (Librarian retention) ·
Wave E (agent subscriptions) · Wave F (MessageArtifact + subject-key/class taxonomy) ·
Wave G (non-Telegram channels) · Wave H (definition-of-done live audit).
