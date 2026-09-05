# Communications Gateway — Production ACTIVE Checklist

**Status:** All gates **unchecked**. ACTIVE is **not** authorized.  
**Current production mode:** **OFF**  
**This Phase 11 packet does not flip ACTIVE.**

Use this list only when operator-approved cutover is intentionally started after SHADOW + CANARY evidence.

---

## Hard gates (must all be checked before ACTIVE)

### Control plane

- [ ] `COMMS_GATEWAY_MODE` default in production config remains documented; ACTIVE set only via explicit operator change (not a repo default).  
- [ ] Deployed artifact SHA matches signed activation packet / attestation.  
- [ ] `mode_diagnostics()` on production hosts reviewed pre- and post-change.  
- [ ] Rollback drill completed: revert to OFF within agreed RTO (`docs/deployment/rollback-plan.md`).

### Telegram / bypass

- [ ] Telegram chokepoint baseline **empty** (Phase 9 complete — zero bypass producers).  
- [ ] Provider chokepoint baseline empty (or only approved gateway-mediated adapters).  
- [ ] Runtime `require_event_id` enforced on Telegram egress path for activated classes.  
- [ ] No dual-send path for activated message classes (legacy send disabled or gated for those classes).

### Tests and evidence

- [ ] Unit suite green: `pytest tests/test_comms_*.py tests/test_communications_portal.py` (paste in `docs/testing/unit-results.md`).  
- [ ] Chokepoint ratchet tests green.  
- [ ] SHADOW compare evidence archived with acceptable match rates for activated classes.  
- [ ] Canary results completed for each activated message class (`docs/deployment/canary-results.md`).  
- [ ] Portal / `/v3/communications` health shows ledger visibility without claiming false delivery ownership pre-cutover.

### Ledger and safety

- [ ] CommunicationEvent + ChannelDelivery migrations applied and verified on production DSN.  
- [ ] Idempotency behavior verified under retry (no double-send).  
- [ ] Protected-fact classes (`approval`, `protection_incident`, …) fail closed without facts/sources.  
- [ ] Librarian legal hold / dry-run expiry understood; no accidental purge job in ACTIVE window.  
- [ ] Agent consumption receipts cannot self-certify truth.

### Scope

- [ ] Message-class allowlist for ACTIVE explicitly listed (Telegram first).  
- [ ] Non-Telegram channels **not** activated unless Phase 10 adapters are gateway-mediated and canaried.  
- [ ] Operator sign-off recorded (name, UTC time, SHA).

---

## Post-activation verification (still unchecked until done)

- [ ] Spot-check SENT deliveries have `provider_message_id` / coordinates.  
- [ ] Bypass monitors remain at zero for Telegram.  
- [ ] Shadow/canary dashboards show no unexplained mismatch surge.  
- [ ] Rollback contact and OFF procedure linked from incident runbook.

---

## Explicit statement

**Production remains OFF.** Checking boxes above is future work. Shipping this file does not constitute activation.
