# Communications Gateway — Gap Analysis

**Attested SOURCE_COMMIT:** `17e30dcbb9a091f2fb9916f3c0d4ccabd5c5e72e`  
**Maps:** design intent (Drive remediation + CommunicationEvent@v2) ↔ runtime/code truth

Classification key: **LIVE** · **LIVE BUT PARTIAL** · **BUILT_DARK** · **DISCONNECTED** · **DESIGN_ONLY** · **ABSENT**

---

## P0 — Truth and control

| Target capability | Class | Gap | Close-in phase |
|---|---|---|---|
| Exact live SHA attestation | LIVE | Continuous re-attest on each deploy | Phase 0 (ongoing) |
| Sender disposition ledger | LIVE BUT PARTIAL | 166 MIGRATE owners TBD | Phase 0 sign-off |
| Zero bypass traffic | LIVE BUT PARTIAL | Telegram: 45 producers / 133 violations (ratchet). Slack/SMTP/Twilio/Meta: static ratchet + approved adapters landed Phase 2; Telegram zero still Phase 9 | Phase 2 done (static) · PR-9 for Telegram zero |
| Universal `event_id` before provider call | BUILT_DARK (Phase 1 client OFF) | Ledger + `publish_communication` exist; producers not yet migrated; delivery not owned | Phase 1 done · migrate Phase 5+ · enforce Phase 2 |
| Fail closed on missing provenance / protected facts / retention / recipient policy | ABSENT / partial CIO only | Not universal | Phase 1 + 5 |
| Dual-path CIO residual eliminated | LIVE BUT PARTIAL | Scanner direct-send vs outbox worker | Phase 2–3 / CIO cutover |

---

## P1 — Gateway and memory

| Target capability | Class | Gap | Close-in phase |
|---|---|---|---|
| CommunicationEvent@v2 ledger | BUILT_DARK | Schema + client + tests landed; not wired to producers; mode OFF | Phase 1 done · adoption Phase 5+ |
| Generalize CIO lineage + alert outbox | LIVE foundations / ABSENT universal | Two parallel stacks + legacy | Phase 1–3 |
| Delivery ledger (all channels) | BUILT_DARK | `ChannelDelivery@v1` + migration + auto-RESERVED stubs on publish; no provider settlement ownership yet | Phase 3 done · wire adapters later |
| Telegram adapter behind gateway only | LIVE BUT PARTIAL | Approved transport exists; bypasses remain | Phase 2, migrate Phase 9 |
| Email / Slack / WhatsApp gateway adapters | BUILT_DARK | `send_via_gateway` records by default; deliver only in CANARY/ACTIVE | Phase 10 done · adoption later |
| Subject memory / SubjectThread@v1 | BUILT_DARK | Package + migration + publish hook; not CC-visible yet | Phase 4 done · Phase 7 surfaces |
| `/v3/communications` | BUILT_DARK | Hub+API in tree; not attested on live CURRENT until deploy | Phase 7 done · deploy/attest |
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
| CommunicationEvent@v2 | BUILT_DARK (code+migration; not producer-adopted) |
| SubjectThread@v1 | BUILT_DARK (`subject_memory` + SQL) |
| MessageArtifact@v1 | ABSENT |
| CurationReceipt@v1 | BUILT_DARK (`curation.py`) |
| ChannelDelivery@v1 | BUILT_DARK (`delivery.py` + SQL; SHADOW stubs) |
| RetentionDecision@v1 | BUILT_DARK (`librarian.py`) |
| AgentConsumptionReceipt@v1 | ABSENT |

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
| Every communication has CommunicationEvent | NO |
| Every delivery has receipts | NO (partial) |
| Every channel through gateway | NO |
| Agents via governed subscriptions | NO |
| Librarian retention enforced | NO |
| CC reflects ledger | NO (`/v3/communications` absent) |
| No direct sender paths | NO |
| Tests + rollback + SHA match + `/docs` final | NO |

---

## Recommended close order (unchanged)

1. Finish Phase 0 owner sign-off.  
2. Phase 1 CommunicationEvent (OFF).  
3. Phase 2 enforcement ratchet → zero.  
4. Phase 3 delivery ledger + Telegram SHADOW.  
5. Migrate critical producers → CANARY.  
6. CC workspace, Librarian, agents, other channels.  
7. ACTIVE only with empty bypass baseline + evidence pack.
