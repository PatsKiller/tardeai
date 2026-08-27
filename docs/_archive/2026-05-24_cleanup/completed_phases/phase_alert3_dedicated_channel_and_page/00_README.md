# ALERT-3 — Dedicated Proposal Channel and Page

**Status:** COMPLETE

## Telegram Routing

Proposal decision alerts now route via `telegram_alert_routing_policy.py`:
- `TRADEAI_PROPOSAL_ALERT_CHAT_ID` → dedicated proposal channel
- `TRADEAI_GENERAL_ALERT_CHAT_ID` → general operations channel
- Falls back to `TELEGRAM_CHAT_ID` if dedicated not configured
- Supports forum topics via `THREAD_ID`
- All chat IDs redacted in logs/docs

## Command Center Page

**Proposal Alerts / Decision Queue**
- Route: `/v2/proposal-alerts`
- Menu: Trading → Proposal Alerts
- Shows: alert type, verdict, R:R, spread, quote provider, blockers, age
- Summary cards: ready/blocked/review/pending counts
- Links to Paper Proposals for full details

## Menu After ALERT-3

Trading tab: 13 items (+1 Proposal Alerts)

## Tests

14/14 ALERT-3 + 17/17 ALERT-2 + 10/10 MISS-1 regression.
