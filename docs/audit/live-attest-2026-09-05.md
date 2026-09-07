# Communications Gateway — Live Attestation (re-attest, post #862/#864/#868, then #871/#872/#873)

```
Status: ACTIVE
as_of: 2026-09-07T11:33:00-04:00
Measured at: served build 3cb740e4c69380fe9355da6b4857a94cf21e6c27 (PR #874 Wave E + docs)
```

Supersedes `docs/audit/runtime-attestation.md` (which cited `17e30dcbb` and predated
production ACTIVE). All values below were read live via HTTP from the served release or
from `origin/main`; nothing here is a `[DOC-CLAIM]` about runtime.

---

## 0. Re-attestation (2026-09-07) — served `3cb740e4c`, mode **CANARY** `[VERIFIED]`

The `f88853e89` re-attestation below (2026-09-05) was itself superseded. On 2026-09-07
PR #874 (Wave E agent consumption + docs catch-up, head `d18d81208`) merged to `origin/main`
as `3cb740e4c69380fe9355da6b4857a94cf21e6c27` and was deployed. Independent read-only
validation confirmed: two-parent merge ancestry, 10/10 CI green, `SOURCE_COMMIT` == merge
SHA, `CURRENT` → `3cb740e4c-main-exact-phase2-20260907-105152`, mode **CANARY** /
`owned_classes=["ops"]`. See `docs/ops/COMMS_GATEWAY_GO_LIVE_RUNBOOK.md` and the validation
evidence archive `/tmp/pr874-validation-20260907.tar.gz` (sha256 `9f77803d0f60d1b9de0a84ea0b6413f98fae9a4c7d8fb37367e33375ad9d1d92`).

---

## 0. Re-attestation (later 2026-09-05) — served `f88853e89`, mode **CANARY** `[VERIFIED]`

The body of this document (sections 1–7) attests the served build `faf8c05d9` in mode
**ACTIVE**, read at 10:45 ET. That state has since been superseded. This section re-attests
the current live state, read at 13:56 ET. **The mode is now CANARY, not ACTIVE** — the
earlier ACTIVE posture was reverted after a short operator soak (see
`docs/deployment/canary-results.md`).

### 0.1 Served build identity `[VERIFIED]`

Command: `curl -s http://127.0.0.1:7777/v3/build-meta.json`

| Field | Value |
|---|---|
| `git_sha` / `build_sha` / `source_sha` / `source_commit` | `f88853e89e53fdd63725acccb064ca1395e0bf34` |
| `ui_version` | `3.14+mtoonq76` |
| `built_at` | `2026-09-05T17:55:09.682Z` |
| `branch` / `release_label` | `main` / `main-exact-phase2` |

`CURRENT` resolves to
`~/trade-ai-releases/portfolio-server/f88853e89-main-exact-phase2-20260905-135414`
(`readlink -f`), so the served SHA is `f88853e89` — the merge of PR #873 (poller rewiring).

### 0.2 Gateway mode and ownership `[VERIFIED]`

Command: `curl -s http://127.0.0.1:7777/api/v2/communications/health`

```json
"mode": "CANARY",
"delivery_owned": true,
"owned_classes": ["ops"],
"mode_diagnostics": { "mode": "CANARY", "reason": "env:COMMS_GATEWAY_MODE",
                     "default": "OFF", "delivery_owner": "gateway_canary_or_active",
                     "valid_modes": ["OFF","SHADOW","CANARY","ACTIVE"] },
"ledger": { "source": "db", "db_reachable": true, "events_source": "db",
            "deliveries_source": "db", "subjects_source": "db" }
```

The host-local systemd drop-in
`~/.config/systemd/user/portfolio-server.service.d/32-comms-gateway-mode.conf` reads
`[CODE]`:

```
Environment=COMMS_GATEWAY_MODE=CANARY
Environment=COMMS_GATEWAY_CANARY_CLASSES=ops
Environment=COMMS_GATEWAY_CANARY_CHATS=6993102664,8797974247
```

So the live posture is **CANARY**, ownership `ops` only, filtered to the two operator
chats above. There is **no ACTIVE** class today; the `ACTIVE_CLASSES=ops` drop-in from the
earlier soak was replaced by the CANARY drop-in.

### 0.3 Merge line `[VERIFIED]`

Command: `gh pr view <n> --json number,state,mergeCommit` and `git log origin/main --oneline -8`

| PR | Title | State | Merge SHA |
|---|---|---|---|
| #871 | comms: Wave A/B — live re-attest, F1 stub-settle, F3 class vocab | MERGED | `47576f7fa5b8230526df1150b810c5e8f643e8ce` |
| #872 | fix(comms): surface LEGACY_DELIVERED settle failure | MERGED | `d38003fbb1dc96653f7ef231abd5878936425c89` |
| #873 | feat(comms): rewire callback poller to gateway inbound checkpoint (Wave C) | MERGED | `f88853e89e53fdd63725acccb064ca1395e0bf34` |
| #874 | feat(comms): expose agent consumption via portal + CC Agent Memory view (Wave E) | OPEN | — (no merge) |

`origin/main` head is `f88853e89` (merge of #873); the ancestry is
`…faf8c05d9 → 47576f7fa (#871) → d38003fbb (#872) → f88853e89 (#873)`.

### 0.4 What moved since the `faf8c05d9` attestation

- **Mode**: ACTIVE → **CANARY** (operator reverted after a ~40 min soak; the ACTIVE drop-in
  was judged premature). CANARY now carries `CANARY_CHATS=6993102664,8797974247`.
- **F1 fixed and migrated**: non-owned deliveries now settle `LEGACY_DELIVERED` (PR #871
  code + migration applied to prod DB; PR #872 surfaces settle failures). The
  `LEGACY_DELIVERED` value is present in the delivery-status constraint.
- **F3 fixed**: `scripts/lib/comms/vocabulary.py` canonicalizes `operator_alert`/`ops_alert`/
  `health*` → `ops`; unknown classes pass through, never coerced.
- **Wave C inbound landed**: `scripts/lib/comms/inbound.py` (claim/commit/checkpoint,
  quarantine, `build_inbound_event`) with `communication_inbound_checkpoint` and
  `communication_inbound_quarantine` tables applied to prod; poller rewired in PR #873.
- **Wave A–F artifacts**: `MessageArtifact@v1`, librarian purge receipts, agent contracts,
  curation gate — built (see `docs/audit/gap-analysis.md`).

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
