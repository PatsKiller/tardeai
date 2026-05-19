# Telegram Noise Audit
Generated: 2026-05-19T20:13:04.200194+00:00  |  Window: 14 days

## Summary
- Total alerts: **11**
- Estimated actionable: **11**
- Estimated non-actionable (noise): **0**

## By Alert Type
| rebalance_stale | 3 |
| api_credits_depleted | 3 |
| paper_trade_monitor | 3 |
| youtube_backfill_progress | 1 |
| premarket_catalyst | 1 |

## By Tier
| INFO | 6 |
| URGENT | 3 |
| DASHBOARD_ONLY | 1 |
| DIGEST | 1 |

## By Action Taken
| sent_telegram | 9 |
| dashboard_only | 1 |
| queued_morning_digest | 1 |

## Noise Estimates
- WAIT/AVOID in Trade AI messages: **0**
- STOP repeats: **0**
- Iris audit notifications: **0**
- Cron success pings: **0**

## Top Spam Categories
- rebalance_stale: 3
- api_credits_depleted: 3
- paper_trade_monitor: 3
- youtube_backfill_progress: 1
- premarket_catalyst: 1

## Recommended Routing
- **WAIT/AVOID signals**: Suppress from Telegram, log-only
- **Cron success pings**: Suppress from Telegram, dashboard badge only
- **STOP repeats**: Deduplicate — send once per symbol per 24h
- **Iris audit**: Daily digest instead of per-event
- **Actionable alerts (P0/P1)**: Keep real-time Telegram delivery
