# OPS-HYGIENE-1 — Operator Command Surface, Actionable Alert Routing, Dashboard Cleanup

**Status:** COMPLETE (13/14 done, 1 partial)

## What Was Delivered

1. **Central alert router** (`scripts/telegram_alert_router.py`):
   - `classify_alert()` -> P0_INTERRUPT / P1_DIGEST / P2_DASHBOARD_ONLY / P3_LOG_ONLY
   - `should_send_telegram()` with dedupe + rate limiting
   - In-memory suppression log for audit
   - Configurable via `config/operator_alert_policy.yaml`

2. **telegram_alert.py patched**: `send_telegram()` now routes through router
   - P2/P3 messages suppressed (WAIT, AVOID, RVOL, Iris, cron success, Drive sync)
   - P1 messages deduped (stops 2/symbol/day, GO 3/hour)
   - P0 always passes (proposals, execution failures, GO with trade plan)
   - `bypass_router=True` for critical system alerts

3. **Estimated Telegram reduction: 93%** (844 -> 54 messages/14d)
   - P0 preservation: 100%

4. **Operator reports**:
   - Noise audit, command surface, page map, Drive validation, cron hygiene

5. **Operator alert policy config** (`config/operator_alert_policy.yaml`)

## What Is Partial

- 7 scripts with own `send_telegram` definitions not yet routed (deferred to OPS-HYGIENE-2)

## Tests

34/34 pass.
