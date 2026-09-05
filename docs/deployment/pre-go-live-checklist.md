# Communications Gateway — Pre Go-Live Checklist

**Status:** Live on CURRENT · **ACTIVE for `ops` only**  
**Date:** 2026-09-05  
**Mode:** `COMMS_GATEWAY_MODE=ACTIVE` · `COMMS_GATEWAY_ACTIVE_CLASSES=ops`

## Must be green before merge (PR #862)

- [x] Static Telegram chokepoint: **zero bypasses**
- [x] Provider chokepoint (Slack/SMTP/Twilio/Meta): **zero**
- [x] Inline keyboards + sendDocument restored via approved APIs
- [x] Unit/comms/portal/docs-index tests passing locally
- [x] CI on PR #862 all green
- [x] No unresolved review threads blocking merge

## Production cutover (completed)

- [x] Apply migrations on production DB (11 `communication_*` tables)
- [x] Deploy SHA to `portfolio-server/CURRENT` — `f579053b8` (PR #864 on top of #862)
- [x] Attest `/v3/communications` + `/api/v2/communications/health` on live
- [x] SHADOW compare — match rate **1.0**; evidence under `~/.local/state/cio-phase2-exact-main/comms-shadow-evidence/`
- [x] CANARY: class `ops` — Telegram delivery **SENT**
- [x] Rollback rehearsal (`COMMS_GATEWAY_MODE=OFF`) completed before ACTIVE
- [x] Sign `docs/deployment/production-activation.md` — ACTIVE for **`ops` only**

## Residuals (addressed in follow-up)

- [x] Portal health `delivery_owned` derived from mode + allowlist (`owned_classes`)
- [x] Telegram SENT rows populate `provider_message_id` from transport `message_id`

## Known remaining scope

- Non-`ops` classes still legacy-send + best-effort ledger until canaried
- No new Bitwarden secrets required (mode/allowlist are systemd env flags)
