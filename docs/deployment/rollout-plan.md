# Communications Gateway — Rollout Plan

**Status:** Communications Gateway program documentation (Phases 0–11).
**Date:** 2026-09-05

**Modes:** `OFF` → `SHADOW` → `CANARY` → `ACTIVE` via `COMMS_GATEWAY_MODE`  
**Default forever until operator flip:** **OFF**  
**First channel:** **Telegram**  
**Phase 11 posture:** documentation + SHADOW compare helper only — **no production ACTIVE cutover**.

---

## Principles

1. Ledger before ownership — record CommunicationEvent / ChannelDelivery stubs before claiming egress.  
2. Compare before canary — SHADOW must show legacy vs gateway parity on `subject_key`, `severity`, route intent.  
3. Message-class canary — activate narrow classes first; never “all Telegram” in one step.  
4. Idempotency prevents double-send — same `idempotency_key` / delivery attempt key collapses retries.  
5. Rollback is mode revert — set `COMMS_GATEWAY_MODE=OFF`; keep ledger rows.

---

## Stage 0 — OFF (current production)

| Item | State |
|---|---|
| `COMMS_GATEWAY_MODE` | unset / OFF |
| Ledger | May record (memory or DB) |
| Delivery ownership | Legacy paths only |
| Telegram senders | Unmigrated (Phase 9 deferred) |
| Other channel adapters | Phase 10 deferred |

Exit: unit suite green; architecture + audit packets present.

---

## Stage 1 — SHADOW (lab / selected hosts)

| Action | Detail |
|---|---|
| Set mode | `COMMS_GATEWAY_MODE=SHADOW` on **non-prod or single canary host** only |
| Behavior | Ledger + decision compare; **no** gateway delivery ownership |
| Tooling | `scripts/lib/comms/shadow_compare.py` — `compare_legacy_vs_gateway`, `record_shadow_observation`, `shadow_report` |
| Evidence | Archive shadow reports; mismatch triage by field |

Exit criteria:

- Shadow observations collected for Telegram-bound message classes.  
- Mismatch rate understood and either fixed or explicitly waived per class.  
- `delivery_owned` remains False.

---

## Stage 2 — CANARY by message class (Telegram first)

Order of message classes (proposed):

1. `operator_alert` / health-style low-risk notifies  
2. Research / digest classes (non-protected-fact)  
3. `protection_incident` (requires protected_facts + authoritative_sources)  
4. `approval` / broker-adjacent classes last  

Per class:

| Step | Action |
|---|---|
| 1 | Limit recipients / chat IDs via destination policy |
| 2 | Set `COMMS_GATEWAY_MODE=CANARY` only on canary host |
| 3 | Gateway owns delivery **only** for allowlisted class+channel |
| 4 | Record results in `docs/deployment/canary-results.md` |
| 5 | Hold ≥ soak window; expand class list only after green |

**Do not** enable email / Slack / WhatsApp canary until Phase 10 adapters exist behind the gateway.

---

## Stage 3 — ACTIVE (future; blocked)

ACTIVE is allowed only after `docs/deployment/production-activation.md` gates are checked (today: **all unchecked**).

Telegram-first ACTIVE means:

- Empty Telegram chokepoint baseline (Phase 9).  
- Canary evidence for each activated message class.  
- SHA attestation match between deployed artifact and signed packet.  
- Rollback drill documented (`docs/deployment/rollback-plan.md`).

---

## Message-class × mode matrix (target)

| Message class | OFF | SHADOW | CANARY | ACTIVE |
|---|---|---|---|---|
| operator_alert (Telegram) | legacy send | compare | first canary | later |
| research / digest | legacy | compare | second | later |
| protection_incident | legacy | compare | third | later |
| approval / broker_fact / order_state | legacy | compare | last | later |
| Slack / SMTP / WhatsApp | legacy / approved wrappers | n/a until Phase 10 | deferred | deferred |

---

## Explicit non-goals for this packet

- Do **not** migrate Telegram senders (Phase 9).  
- Do **not** implement channel adapters (Phase 10).  
- Do **not** set ACTIVE in any default config or unit fixture as production default.