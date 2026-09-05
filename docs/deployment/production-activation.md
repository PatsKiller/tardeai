# Communications Gateway — Production Mode Checklist (ACTIVE attempted → reverted to CANARY)

**Status:** **CANARY for message class `ops` only** (Telegram).  
**Current production mode:** **CANARY** via systemd `32-comms-gateway-mode.conf`
(`COMMS_GATEWAY_MODE=CANARY`, `CANARY_CLASSES=ops`, `CANARY_CHATS=6993102664,8797974247`).  
**Served SHA:** `f88853e89e53fdd63725acccb064ca1395e0bf34` (`[VERIFIED]` via `/v3/build-meta.json`).  
**Signed:** 2026-09-05T04:31:30Z · operator johnclaw (agent-assisted)

> **Mode correction (2026-09-05T13:56:00-04:00):** an **ACTIVE for `ops`** posture was set
> (`COMMS_GATEWAY_ACTIVE_CLASSES=ops`, cutover SHA `f579053b8` / PR #864) and then **reverted
> to CANARY** after a ~40-minute operator soak that was judged premature. The checklist below
> records the ACTIVE attempt and its gates for provenance; it is **not** the current posture.
> The current live mode is **CANARY**, verified at
> `curl -s http://127.0.0.1:7777/api/v2/communications/health` → `"mode": "CANARY"`.

All other message classes remain legacy-send + best-effort ledger unless added to
`COMMS_GATEWAY_CANARY_CLASSES` (then `COMMS_GATEWAY_ACTIVE_CLASSES` at the eventual ACTIVE step).

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

**Production is CANARY for Telegram message class `ops` only** (filtered to
`CANARY_CHATS=6993102664,8797974247`). The earlier ACTIVE posture was reverted. Expanding
classes requires a new canary row in `canary-results.md` and an allowlist update; moving
back to ACTIVE requires re-checking the gates above against the then-current SHA. Repo
defaults remain OFF.
