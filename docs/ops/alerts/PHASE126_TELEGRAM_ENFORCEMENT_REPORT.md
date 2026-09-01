# Phase 126 — Telegram Actionable-Only Enforcement Report

Status:      HISTORICAL
as_of:       2026-06-01T17:34:15-04:00
Measured at: efcc51365 / not measured

## Telegram Send Path Inventory

| Path | Count | Gated? |
|------|-------|--------|
| Via `send_telegram()` (imports telegram_alert) | 65 scripts | **YES** — routes through telegram_alert_router.py |
| `bypass_router=True` | 1 script (send_closed_trade_digest test mode) | Intentional bypass for test |
| Direct `api.telegram.org/sendMessage` | 34 scripts | **NO** — bypasses router entirely |

## Direct Bypass Scripts (34 — not gated tonight)

These scripts call the Telegram API directly without going through the router. They are a P2 technical debt item — each needs to be refactored to use `send_telegram()`.

Top offenders by noise impact:
1. `pipeline_watchdog.py` — repeated pipeline status
2. `portfolio_alerts.py` — portfolio heat/stop alerts (19× in SIEM)
3. `system_health_alerts.py` — repeated health check alerts
4. `atm_auto_approver.py` — OUTPUT_INVALID noise (59× in SIEM)
5. `pipeline_health_monitor.py` — pipeline failure repeats

## What Was Done Tonight

1. **Phase 125B**: Added 12 P2_SYSTEM_PATTERNS to `telegram_alert_router.py` — these suppress retry_exhausted, safe_flock, maria_stale, atm_output_invalid, llm_complete, false_fixed, lock_timeout, afterhours_stop to dashboard-only
2. **Gated path verified**: 65 scripts using `send_telegram()` are all gated through the router
3. **Direct bypass documented**: 34 scripts identified, need future refactoring
4. **9/9 classification tests pass**: retry noise → P2, actionable stops → P0, approvals → P0

## What Was NOT Done (P2 debt)

- 34 direct-API bypass scripts were not refactored tonight
- These will continue to send Telegram directly until migrated to `send_telegram()`
- Impact: some noisy alerts (pipeline_watchdog, portfolio_alerts) still bypass the gate

## Suppression Runtime Test Results

| Test Message | Classification | Sends Telegram? |
|-------------|---------------|-----------------|
| RETRY_EXHAUSTED overnight_batch | P2_DASHBOARD_ONLY | NO |
| maria_research stale 8d | P2_DASHBOARD_ONLY | NO |
| OUTPUT_INVALID atm_auto_approver | P2_DASHBOARD_ONLY | NO |
| LLM analysis complete | P2_DASHBOARD_ONLY | NO |
| LOCKTIMEOUT orchestrator | P2_DASHBOARD_ONLY | NO |
| after hours stop alert NOC | P2_DASHBOARD_ONLY | NO |
| STOP TRIGGERED RTX action required | P0_INTERRUPT | **YES** |
| APPROVAL READY approve/reject | P0_INTERRUPT | **YES** |
| Morning Brief | P1_DIGEST | YES (if not deduped) |

## Safety
- Proposal writes: ZERO
- Trades: ZERO
- Broker access: ZERO
- Journal mutation: ZERO
- Holdings mutation: ZERO
- Level 7: PROHIBITED
