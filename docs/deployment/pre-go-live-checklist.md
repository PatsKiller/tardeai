# Communications Gateway — Pre Go-Live Checklist

**Status:** Pre-production readiness for PR #862  
**Date:** 2026-09-05  
**Mode:** `COMMS_GATEWAY_MODE` remains **OFF** until canary gates pass

## Must be green before merge

- [x] Static Telegram chokepoint: **zero bypasses**
- [x] Provider chokepoint (Slack/SMTP/Twilio/Meta): **zero**
- [x] Inline keyboards + sendDocument restored via approved APIs
- [x] Unit/comms/portal/docs-index tests passing locally
- [x] CI on PR #862 all green (frontend design tokens + cio-hardening + others)
- [x] No unresolved review threads blocking merge

Note: tip was green at `0d340460f`; after update-from-main CI must re-confirm.

## Must be done before production ACTIVE (not this merge)

- [x] Apply migrations on isolated then production DB (event/delivery/subject/librarian/agent tables) — applied 2026-09-05 to `trade_ai` (11 `communication_*` tables)
- [x] Deploy SHA of approved merge to `portfolio-server/CURRENT` — `c3e2ea319` via exact-main promote 2026-09-05T04:00:09Z
- [x] Attest `/v3/communications` + `/api/v2/communications/health` on live — health `ok`, mode `OFF`, `delivery_owned=false`, `db_reachable=true`; `/v3/communications` HTTP 200
- [x] SHADOW compare period for migrated producers — live DB events compared; production match rate **1.0** (ops+research); evidence `~/.local/state/cio-phase2-exact-main/comms-shadow-evidence/shadow_report.json`; SHADOW publish `gateway_mode_at_write=SHADOW` verified
- [ ] CANARY: limited chats + message classes — blocked on PR #864 Telegram ownership (in CI)
- [x] Rollback rehearsal (`COMMS_GATEWAY_MODE=OFF`) — systemd drop-in SHADOW → remove drop-in → health mode OFF, `delivery_owned=false`
- [ ] Sign `docs/deployment/production-activation.md`

**Live posture after cutover:** code + ledger on CURRENT; `COMMS_GATEWAY_MODE` remains **OFF** (legacy Telegram delivery). ACTIVE not authorized until PR #864 merges + canary evidence.

## Known acceptable residuals at merge

- Gateway does **not** own delivery while OFF (legacy `send_telegram` still delivers)
- Runtime container egress policy not yet enforced
- Not all producers mint CommunicationEvent on every send (SHADOW best-effort only)
