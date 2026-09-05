# Communications Gateway — Production ACTIVE Checklist

**Status:** **ACTIVE authorized for message class `ops` only** (Telegram).  
**Current production mode:** **ACTIVE** via systemd `32-comms-gateway-mode.conf`  
**Deployed SHA (cutover):** `f579053b8accb775c12b7d5e4e35f5533b179fbe`  
**Signed:** 2026-09-05T04:31:30Z · operator johnclaw (agent-assisted)

All other message classes remain legacy-send + best-effort ledger unless added to `COMMS_GATEWAY_ACTIVE_CLASSES`.

---

## Hard gates (must all be checked before ACTIVE)

### Control plane

- [x] `COMMS_GATEWAY_MODE` default in production config remains documented; ACTIVE set only via explicit operator change (not a repo default).  
- [x] Deployed artifact SHA matches signed activation packet / attestation. (`f579053b8` / PR #864)  
- [x] `mode_diagnostics()` on production hosts reviewed pre- and post-change. (ACTIVE / `gateway_canary_or_active`)  
- [x] Rollback drill completed: revert to OFF within agreed RTO (`docs/deployment/rollback-plan.md`).

### Telegram / bypass

- [x] Telegram chokepoint baseline **empty** (Phase 9 complete — zero bypass producers).  
- [x] Provider chokepoint baseline empty (or only approved gateway-mediated adapters).  
- [x] Runtime `require_event_id` enforced on Telegram egress path for activated classes. (via `send_via_gateway`)  
- [x] No dual-send path for activated message classes (legacy send disabled or gated for those classes).

### Tests and evidence

- [x] Unit suite green on PR #864 (canary/ACTIVE tests + CI).  
- [x] Chokepoint ratchet tests green.  
- [x] SHADOW compare evidence archived (match rate 1.0).  
- [x] Canary results completed for each activated message class (`docs/deployment/canary-results.md`).  
- [x] Portal / `/v3/communications` health shows ledger visibility; ownership derived from mode + allowlist (see residuals fix).

### Ledger and safety

- [x] CommunicationEvent + ChannelDelivery migrations applied and verified on production DSN.  
- [x] Idempotency behavior verified under retry (no double-send).  
- [x] Protected-fact classes not in ACTIVE allowlist.  
- [x] Librarian legal hold / dry-run expiry understood; no accidental purge job in ACTIVE window.  
- [x] Agent consumption receipts cannot self-certify truth.

### Scope

- [x] Message-class allowlist for ACTIVE explicitly listed → **`ops` only** (`COMMS_GATEWAY_ACTIVE_CLASSES=ops`)  
- [x] Non-Telegram channels **not** activated.  
- [x] Operator sign-off recorded (name, UTC time, SHA).

---

## Post-activation verification

- [x] Spot-check SENT deliveries (`telegram@v1`, status SENT).  
- [x] Bypass monitors remain at zero for Telegram.  
- [x] Shadow/canary evidence shows no unexplained mismatch surge.  
- [x] Rollback: remove `32-comms-gateway-mode.conf` → OFF (`rollback-plan.md`).

---

## Explicit statement

**Production is ACTIVE for Telegram message class `ops` only.** Expanding classes requires a new canary row in `canary-results.md` and an allowlist update. Repo defaults remain OFF.
