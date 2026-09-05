# Telegram chokepoint — zero bypass closeout

**Date:** 2026-09-05  
**Branch tip (pre-baseline commit):** cohort migrations 1–4  
**Attested check:** `python3 scripts/check_telegram_chokepoint.py` → **pass: zero bypasses**

## Before → after (this finish pass)

| Metric | Before remaining-35 | After |
|---|---|---|
| Baseline files | 35 | **0** |
| Baseline violations | 97 | **0** |

Earlier Phase 9 cohort had already reduced 46/142 → 35/97.

## Method
Four parallel agents migrated remaining producers to `telegram_alert.send_telegram` (or CIO `send_cio_message`).  
`scripts/cio_telegram_bot.py` allowlisted as **APPROVED_INBOUND** (`getUpdates` only).

## Commits
- `a45c8e4f1` cohort 1
- `28e1b2e67` cohort 2
- `8fd6642de` cohort 3
- `670172259` cohort 4
- (this) baseline refresh to empty

## Caveat remediation (follow-up)
Inline keyboards and `sendDocument` were restored through the approved chokepoint:
- `telegram_transport.send_document`
- `telegram_alert.send_telegram(..., reply_markup=..., chat_ids=..., thread_id=...)`
- `telegram_alert.send_telegram_document(...)`
Producers (`proposal_alerter`, `open_trade_monitor`, proposal/time-exit alerts, portfolio report DOCX/PDF paths) again use those APIs — still **zero** static bypasses.

## Honest residual
- Zero **static** bypass ≠ production ACTIVE.
- Runtime egress policy and universal CommunicationEvent adoption remain separate gates.
