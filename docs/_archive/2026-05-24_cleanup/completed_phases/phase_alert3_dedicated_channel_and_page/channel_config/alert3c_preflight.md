# ALERT-3C Preflight

**Date:** 2026-05-18
**Safety:** ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true, holdings=$1,196,478

## Current Telegram Config (Redacted)

| Key | Value |
|-----|-------|
| TELEGRAM_CHAT_ID | ***4247 |
| TRADEAI_GENERAL_ALERT_CHAT_ID | MISSING |
| TRADEAI_PROPOSAL_ALERT_CHAT_ID | MISSING |
| TRADEAI_PROPOSAL_ALERT_THREAD_ID | MISSING |
| TRADEAI_ALERT_ROUTING_MODE | MISSING |

## Status

Dedicated proposal channel not yet configured. Helper scripts created:
- `discover_telegram_chat_id.py` — finds chat IDs from bot updates
- `set_telegram_proposal_channel_env.py` — safely sets .env keys

## Next Steps

1. Operator creates dedicated Telegram group/channel
2. Adds bot to the group
3. Sends a message in the group
4. Runs `discover_telegram_chat_id.py --show-full-id` (local only, not committed)
5. Runs `set_telegram_proposal_channel_env.py --chat-id ID --apply`
6. Verifies with test alert send
