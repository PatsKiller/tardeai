# OPS-HYGIENE-1 Preflight

**Date:** 2026-05-19

## Safety
- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true
- Holdings guard: $1,193,829

## Telegram Sending Landscape
- 143 `send_telegram` call sites across scripts
- Main shared function: `scripts/telegram_alert.py:send_telegram()`
- Most scripts import from `telegram_alert.py` — single interception point
- `alert_dispatch_log`: only 11 entries in 14d (most sends bypass dispatcher)
- Separate senders exist in: system_health_alerts, open_trade_monitor, pipeline_watchdog, premarket_watcher, send_morning_brief, weekly_learning_digest

## Current Problem
- WAIT/AVOID/RVOL-only sent to Telegram
- Repeated STOP_TRIGGERED alerts
- Iris Library/content gap audits in trading channel
- Generic Trade AI Critique summaries
- Cron/Drive sync success messages
- No central routing policy
- 143 send sites, no classification gate
