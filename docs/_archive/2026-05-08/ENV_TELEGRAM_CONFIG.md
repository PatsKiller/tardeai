# Telegram .env Configuration

## Required Variables

```env
# Enable/disable Telegram alerts globally
ENABLE_TELEGRAM=true

# Bot token from @BotFather
TELEGRAM_BOT_TOKEN=<your-bot-token>

# Chat IDs — comma-separated for multiple recipients
# All alerts will be sent to EVERY chat ID listed here
TELEGRAM_CHAT_ID=111111111,222222222
```

## Setup Steps

1. Open Telegram, search **@BotFather**
2. Send `/newbot` — follow prompts, copy the bot token
3. Set `TELEGRAM_BOT_TOKEN=<token>` in `.env`
4. Message your new bot once from each account that should receive alerts
5. Get chat IDs: visit `https://api.telegram.org/bot<token>/getUpdates`
   - Each account that messaged the bot will appear with its `"chat" -> "id"` value
6. Set `TELEGRAM_CHAT_ID=<id1>,<id2>` (comma-separated, no spaces)

## Multiple Recipients

To send alerts to multiple Telegram accounts, list all chat IDs separated by commas:

```env
TELEGRAM_CHAT_ID=6993102664,8797974247
```

Every script that sends Telegram alerts will iterate over all IDs and send to each one independently. If one fails, the others still send.

## Which Scripts Send Telegram Alerts

| Script | Alert Type |
|--------|-----------|
| `telegram_alert.py` | Shared module — all pipeline alerts, GO-tier picks |
| `iris_taxonomy_agent.py` | Hygiene summaries, escalation decisions, library audits, discovery |
| `system_health_alerts.py` | Pipeline health / freshness alerts |
| `morning_digest.py` | Daily morning intelligence digest |
| `weekly_summary_local.py` | Weekly portfolio summary |
| `portfolio_monthly_report.py` | Monthly report + DOCX delivery |
| `portfolio_monthly_synthesis.py` | Monthly synthesis narrative |
| `portfolio_weekly_report.py` | Weekly report + DOCX delivery |
| `portfolio_technical.py` | Technical analysis alerts |
| `portfolio_alerts.py` | Position alerts, rebalance signals |
| `portfolio_live_monitor.py` | Live price alerts |
| `stop_decision_brief.py` | Stop-loss decision briefs |
| `agent_event_router.py` | Agent event notifications |
| `phase3_lookthrough_fetcher.py` | Look-through data staleness |
| `aegis_morning_brief_delivery.py` | Aegis morning brief |
| `alex_retirement_advisor.py` | Alex monthly report, portfolio alerts |

## Error Notify (Pipeline Errors)

```env
# Send Telegram alert when any pipeline stage errors
ERROR_NOTIFY_TELEGRAM=true
```

This uses the same `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` — errors go to all recipients.

## Troubleshooting

- **Only one account gets alerts**: Check that `TELEGRAM_CHAT_ID` has both IDs comma-separated
- **Bot doesn't respond**: Each recipient must have messaged the bot at least once
- **400 Bad Request**: The chat ID is wrong — re-check via `/getUpdates`
- **Markdown parse errors**: Some scripts use `parse_mode=Markdown`, others `HTML`. If a message has unescaped special chars (`_`, `*`, `` ` ``), the API rejects it. The shared `telegram_alert.py` uses Markdown; most inline senders use HTML.
