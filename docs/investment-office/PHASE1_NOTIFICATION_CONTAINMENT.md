# PHASE 1 CLOSEOUT — Notification Containment

**UTC:** 2026-08-14
**Branch:** wt/cio-phase1-notify (from origin/main c330a117)
**Authority:** READ_ONLY_ADVISORY unchanged

## Changes

| File | Change |
|------|--------|
| `scripts/lib/cio_telegram_transport.py` | **NEW** CIO-only transport, materiality, semantic dedupe, pytest interdict |
| `scripts/lib/cio_theses.py` | Thesis publish no longer calls general `send_telegram` |
| `scripts/lib/cio_notification_delivery.py` | Live adapter uses TELEGRAM_CIO_* only |
| `scripts/lib/cio_telegram_converse.py` | Allowlist no longer falls back to TELEGRAM_CHAT_ID |
| `scripts/telegram_transport.py` | HTTP interdict under pytest / CIO_TELEGRAM_INTERDICT |
| `tests/conftest.py` | Autouse monkeypatch blocks all send_message |
| `tests/test_cio_phase1_notification_containment.py` | **NEW** fixtures A/B/Living desk + isolation |

## Env (names only)

| Var | Role |
|-----|------|
| TELEGRAM_CIO_BOT_TOKEN | CIO bot only |
| TELEGRAM_CIO_CHAT_IDS / TELEGRAM_CIO_ALLOWLIST | CIO allowlist only |
| CIO_THESIS_TELEGRAM | Default **0** — thesis bumps silent |
| AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY | Required for live CIO send |
| CIO_TELEGRAM_INTERDICT | Force block |

## Proof

- Fixtures `A`, `B`, `Living desk thesis`, `des` → `not_material` / never delivered
- Default thesis telegram off
- Semantic dedupe suppresses second identical body
- Delivery worker reads CIO env, not general
- Shadow worker never live
- REAL TELEGRAM SENDS: 0
- BROKER CALLS: 0

## Tests

```
tests/test_cio_phase1_notification_containment.py  11 passed
```

## Next phase allowed

Phase 2 (cash/capital ledger) — YES after this branch is reviewed/merged or continued in worktree.

## REAL TELEGRAM SENDS: 0
## BROKER CALLS: 0
## SECRETS PRINTED: 0
## FINANCIAL AUTHORITY CHANGED: NO
