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

## Honest residual
- Zero **static** bypass ≠ production ACTIVE.
- Some migrations flattened inline keyboards / `sendDocument` into text+path notices via wrapper.
- Runtime egress policy and producer→CommunicationEvent adoption remain separate gates.
