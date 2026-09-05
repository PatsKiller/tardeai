# Communications Gateway — Rollback Plan

**Status:** Communications Gateway program documentation (Phases 0–11).
**Date:** 2026-09-05

**Primary control:** revert `COMMS_GATEWAY_MODE` to **OFF**  
**Ledger:** keep CommunicationEvent / ChannelDelivery / subject / curation / retention / agent rows  
**Double-send:** prevented by idempotency keys on event + delivery attempt

---

## When to roll back

- Canary mismatch spike (subject_key / severity / route intent) vs legacy.  
- Unexpected dual delivery or provider errors attributable to gateway ownership.  
- Chokepoint / bypass regression during migration.  
- Operator judgment — any doubt defaults to OFF.

---

## Immediate rollback (runtime)

1. Set environment / unit override:

   ```bash
   export COMMS_GATEWAY_MODE=OFF
   # or unset COMMS_GATEWAY_MODE
   ```

2. Restart gateway-consuming services / workers so `resolve_mode(refresh=True)` / process restart picks up OFF.  
3. Confirm `get_gateway_mode(refresh=True) == "OFF"` and `mode_diagnostics()["delivery_owner"] == "legacy_or_none"`.  
4. Leave DB ledgers intact — do **not** truncate `communication_events` or delivery tables as part of rollback.  
5. Legacy Telegram / approved provider paths continue to send; SHADOW/CANARY ownership stops.

---

## Why this does not double-send

| Mechanism | Behavior |
|---|---|
| Event `idempotency_key` | Retries of the same producer observation collide; no second logical event |
| Delivery attempt idempotency | `event_id + channel + attempt_id` reservation collapses duplicates |
| OFF / SHADOW ownership rule | Gateway must not claim `delivery_owned`; legacy remains sole egress owner |
| CANARY → OFF | Gateway stops owning allowlisted classes; in-flight RESERVED stubs settle or expire without a second legacy send if producers are coordinated |

**Operator note:** During CANARY, producers for allowlisted classes must not also call legacy send for the same observation. Rollback to OFF restores legacy-only send; do not manually “catch up” with a second fire for already-SENT gateway deliveries — reconcile via ledger `provider_message_id` / coordinates instead.

---

## Data retention on rollback

- Keep: events, outbox intents, delivery attempts, subject membership, curation receipts, retention decisions, agent consumption receipts.  
- Safe to leave RESERVED / FAILED rows; they are audit evidence.  
- Librarian expiry continues to respect legal hold; rollback does not imply purge.

---

## Verification after rollback

- [ ] `COMMS_GATEWAY_MODE` resolves OFF on all production hosts.  
- [ ] No process still reports CANARY/ACTIVE in diagnostics.  
- [ ] Legacy health/alert Telegram path still functions.  
- [ ] Unit suite still green: `pytest tests/test_comms_*.py tests/test_communications_portal.py -q`.  
- [ ] Incident note filed with pre-rollback mode, SHA, and shadow/canary evidence pointers.

---

## Related

- Rollout stages: `docs/deployment/rollout-plan.md`  
- Activation checklist (unchecked): `docs/deployment/production-activation.md`