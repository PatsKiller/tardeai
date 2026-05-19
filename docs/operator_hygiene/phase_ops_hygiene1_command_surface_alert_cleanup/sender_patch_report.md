# OPS-HYGIENE-1 — Sender Patch Report

## Approach

Instead of patching 143 individual call sites, we patched the single shared function:

**`scripts/telegram_alert.py:send_telegram()`** — the main Telegram send function imported by ~90% of scripts.

The function now routes through `telegram_alert_router.should_send_telegram()` before sending. Messages classified as P2/P3 are suppressed. P1 messages are deduped. P0 always sends.

## Files Patched

| File | Change |
|------|--------|
| `scripts/telegram_alert.py` | `send_telegram()` now calls router; added `bypass_router` param; original send logic moved to `_raw_send_telegram()` |
| `scripts/telegram_alert_router.py` | New — central classification, dedupe, rate limiting |
| `config/operator_alert_policy.yaml` | New — operator-configurable alert rules |

## Senders Routed Through Central Router (via telegram_alert.py import)

All scripts that `from telegram_alert import send_telegram` are automatically routed:
- continuous_runner.py (Trade AI LIVE)
- alerting.py (general alerts)
- aegis_overnight.py (Aegis alerts)
- finviz_health_check.py / finviz_ingestion.py
- credential_monitor.py
- auto_research.py
- agent_watchlist_engine.py
- generate_daily_intelligence_report.py
- api_v2.py (journal reminder)

## Senders With Own send_telegram (NOT auto-routed)

These define their own `send_telegram` locally and bypass the central function:
- `system_health_alerts.py` — own send function
- `open_trade_monitor.py` — own send function with dry_run
- `pipeline_watchdog.py` — own send function
- `send_morning_brief.py` — own send with chat_ids param
- `premarket_watcher.py` — own send function
- `agent_event_router.py` — own `_send_telegram`
- `alert_dispatcher.py` — own `_send_telegram` wrapper

**These are deferred** — they need individual patches in a future phase (OPS-HYGIENE-2).
Most are low-volume or already partially gated.

## Risk Controls

- `bypass_router=True` parameter allows critical system alerts to skip routing
- P0 patterns match before P2/P3, so actionable alerts are never suppressed
- Suppression log maintained in memory for audit
- Policy is YAML-configurable, no code change needed to adjust thresholds
