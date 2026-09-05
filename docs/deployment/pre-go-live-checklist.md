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

- [ ] Apply migrations on isolated then production DB (event/delivery/subject/librarian/agent tables)
- [ ] Deploy SHA of approved merge to `portfolio-server/CURRENT`
- [ ] Attest `/v3/communications` + `/api/v2/communications/health` on live
- [ ] SHADOW compare period for migrated producers
- [ ] CANARY: limited chats + message classes
- [ ] Rollback rehearsal (`COMMS_GATEWAY_MODE=OFF`)
- [ ] Sign `docs/deployment/production-activation.md`

## Known acceptable residuals at merge

- Gateway does **not** own delivery while OFF (legacy `send_telegram` still delivers)
- Runtime container egress policy not yet enforced
- Not all producers mint CommunicationEvent on every send (SHADOW best-effort only)
