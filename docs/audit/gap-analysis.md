# Communications Gateway — Gap Analysis

**Attested SOURCE_COMMIT:** `faf8c05d9cfa149c2efd7cadfb05a5bd7b3644d1` (served; re-attested `docs/audit/live-attest-2026-09-05.md`)  
**Maps:** design intent (Drive remediation + CommunicationEvent@v2) ↔ runtime/code truth

Classification key: **LIVE** · **LIVE BUT PARTIAL** · **BUILT_DARK** · **DISCONNECTED** · **DESIGN_ONLY** · **ABSENT**

---

## P0 — Truth and control

| Target capability | Class | Gap | Close-in phase |
|---|---|---|---|
| Exact live SHA attestation | LIVE | Continuous re-attest on each deploy | Phase 0 (ongoing) |
| Sender disposition ledger | LIVE BUT PARTIAL | 166 MIGRATE owners TBD | Phase 0 sign-off |
| Zero bypass traffic | LIVE BUT PARTIAL | Telegram: 45 producers / 133 violations (ratchet). Slack/SMTP/Twilio/Meta: static ratchet + approved adapters landed Phase 2; Telegram zero still Phase 9 | Phase 2 done (static) · PR-9 for Telegram zero |
| Universal `event_id` before provider call | LIVE (owned `ops`) | `publish_communication` + `send_via_gateway` wired into `telegram_alert`; non-owned classes still legacy-send with a best-effort stub | Phase 1 done · migrate Phase 5+ · enforce Phase 2 |
| Fail closed on missing provenance / protected facts / retention / recipient policy | ABSENT / partial CIO only | Not universal | Phase 1 + 5 |
| Dual-path CIO residual eliminated | LIVE BUT PARTIAL | Scanner direct-send vs outbox worker | Phase 2–3 / CIO cutover |

---

## P1 — Gateway and memory

| Target capability | Class | Gap | Close-in phase |
|---|---|---|---|
| CommunicationEvent@v2 ledger | LIVE | Schema + client + tests landed; producer-adopted via `telegram_alert`; mode ACTIVE for `ops` | Phase 1 done · adoption Phase 5+ |
| Generalize CIO lineage + alert outbox | LIVE foundations / ABSENT universal | Two parallel stacks + legacy | Phase 1–3 |
| Delivery ledger (all channels) | LIVE BUT PARTIAL | `ChannelDelivery@v1` + migration + auto-RESERVED stubs; owned `ops` settles SENT, non-owned stubs stay RESERVED (F1) | Phase 3 done · wire adapters later |
| Telegram adapter behind gateway only | LIVE BUT PARTIAL | Approved transport exists; `ops` owned; other classes legacy | Phase 2, migrate Phase 9 |
| Email / Slack / WhatsApp gateway adapters | BUILT_DARK | `send_via_gateway` records by default; deliver only in CANARY/ACTIVE | Phase 10 done · adoption later |
| Subject memory / SubjectThread@v1 | LIVE BUT PARTIAL | Package + migration + publish hook; subject_key body-derived (F2), not domain-aware | Phase 4 done · Phase 7 surfaces |
| `/v3/communications` | LIVE | Hub+API served; HTTP 200 on `faf8c05d9` | Phase 7 done · deploy/attest |
| Controlled curation + CurationReceipt | BUILT_DARK | Tier policy + receipts + protected-fact fallback; no live LLM wiring | Phase 5 done · use in producers later |

---

## P2 — Institutional memory and agents

| Target capability | Class | Gap | Close-in phase |
|---|---|---|---|
| Librarian retention for communications | BUILT_DARK | RetentionDecision@v1 + dry_run expiry; not scheduled on prod | Phase 6 done · schedule later |
| Knowledge promotion with provenance | DESIGN_ONLY / partial research paths | Chat must not auto-become truth | Phase 6 |
| AgentConsumptionReceipt (all agents) | BUILT_DARK | agent_contracts module + receipts; producers not subscribed yet | Phase 8 done · wire agents |
| CIO governed subscription | LIVE BUT PARTIAL | Best consumer; still dual-path | Phase 8 |
| Hermes / Advisory consumption | LIVE BUT PARTIAL / BUILT_DARK | Not one ledger | Phase 8 |
| Darwin / Maria first-class contracts | ABSENT | No dedicated governed senders | Phase 8 (later) |
| Metrics (dup rate, ack, stale-link, cost, decision impact) | ABSENT / partial CIO metrics | Need gateway metrics plane | Phase 8+ |

---

## Contract coverage matrix

| Contract | Status |
|---|---|
| CommunicationEvent@v2 | LIVE (code+migration; producer-adopted for owned classes) |
| SubjectThread@v1 | LIVE BUT PARTIAL (`subject_memory` + SQL; body-derived keys) |
| MessageArtifact@v1 | ABSENT |
| CurationReceipt@v1 | BUILT_DARK (`curation.py`) |
| ChannelDelivery@v1 | LIVE BUT PARTIAL (`delivery.py` + SQL; owned settles, legacy stubs orphaned) |
| RetentionDecision@v1 | BUILT_DARK (`librarian.py`) |
| AgentConsumptionReceipt@v1 | BUILT_DARK (`agent_contracts.py`) |

Existing near-analogs to **adapt**, not keep as parallel truths:

- `AlertEvent` + `publish_event` → producer adapter into CommunicationEvent
- CIO `NotificationDecision@v1` / signal gate → producer adapter + policy lessons
- Advisory `notification_broker` SHADOW → ingest compression patterns

---

## Mode vocabulary gap

| Product language | Alert plane | CIO plane |
|---|---|---|
| OFF | OFF | INTERDICTED / dry |
| SHADOW | SHADOW | worker `--mode shadow` / PREPARE_ONLY |
| CANARY | **missing** in alert enum | `CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY` etc. |
| ACTIVE | ACTIVE | CIO_ONLY_LIVE + live worker |

**Gap:** document and implement an explicit CANARY class for gateway cutover (limited channels/recipients/classes) without overloading unrelated flags.

---

## Documentation gap

Required `/docs/audit|architecture|testing|deployment|final` tree is **not** complete. This Phase 0 packet creates `docs/audit/*` only. Architecture/testing/deployment/final docs are Phase 1+.

---

## Acceptance gap vs definition of done

| DoD item | Now |
|---|---|
| Every communication has CommunicationEvent | PARTIAL (owned `ops` yes; legacy best-effort stub) |
| Every delivery has receipts | PARTIAL (owned settle SENT; legacy stubs orphaned — F1) |
| Every channel through gateway | NO |
| Agents via governed subscriptions | NO |
| Librarian retention enforced | NO |
| CC reflects ledger | PARTIAL (`/v3/communications` 200) |
| No direct sender paths | PARTIAL (chokepoint baseline empty; `ops` mediated) |
| Tests + rollback + SHA match + `/docs` final | PARTIAL (SHA `faf8c05d9` attested) |

---

## Wave A findings (live re-attest 2026-09-05)

See `docs/audit/live-attest-2026-09-05.md` for quoted evidence. Summary:

- **F1** non-owned deliveries stuck `RESERVED`, never settle → ledger reads as a queue that never drains.
- **F2** `subject_key` is body-derived (`telegram:{class}:{body[:48]}`), not domain-aware.
- **F3** `message_class` taxonomy inconsistent (`ops` / `ops_alert` / `operator_alert` / `health` / …); `owned_classes=["ops"]` catches a sliver.
- **F4** test-suite leakage residue in prod DB (`wamid.test_1`); fixed by `edcf137f8` + `c2986912b`.
- **F5** `retention_class` drift (`operational`, `operational_30d`, `ops_7d`, `inbound_7d`, `none`).

**Remediation (this wave):** F1 and F3 are fixed in code, not yet deployed.
- F1 → `LEGACY_DELIVERED` terminal delivery status (`delivery.py` + migration `2026_09_05_communication_delivery_legacy_status.sql`); `_best_effort_comms_publish` settles the auto-reserved stub.
- F3 → `scripts/lib/comms/vocabulary.py` canonical vocabulary; `publish_communication` normalizes `operator_alert`/`ops_alert`/`health*` → `ops` (unknown classes pass through, never coerced).

Ownership is unchanged: `COMMS_GATEWAY_ACTIVE_CLASSES` still owns `ops` only; the
canary that folds the legacy `operator_alert` producers into gateway ownership is the
operator-approved Wave B step (proposed, not applied).

---

## Recommended close order (unchanged)

1. Finish Phase 0 owner sign-off.  
2. Phase 1 CommunicationEvent (OFF).  
3. Phase 2 enforcement ratchet → zero.  
4. Phase 3 delivery ledger + Telegram SHADOW.  
5. Migrate critical producers → CANARY.  
6. CC workspace, Librarian, agents, other channels.  
7. ACTIVE only with empty bypass baseline + evidence pack.
