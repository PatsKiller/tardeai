# REGIME-CRON-1 Alerting Report

## Existing Alerts

The classifier already has regime-change alerting via `_alert_regime_change()` which calls `dispatch_alert()` with tier=ALERT. This fires when the regime label changes between runs.

## Stale Regime Alerting

The classifier health check cron already exists:
```
55 7 * * 1-5  scripts/monitoring/classifier_health_check.py
```

With the code fix applied, the classifier now writes fresh snapshots on every run. If it fails, the run log records the failure and the health check can detect staleness.

The `run_regime_cron1_health.py` script provides operator-facing health assessment:
- `health: "stale"` when snapshot age > 26 hours
- `health: "last_run_failed"` when latest run log shows failure
- `recommended_action` for each health state

## Telegram Routing

Regime change alerts route through the existing `dispatch_alert()` → `telegram_alert_router.py` pipeline. The classifier health check logs to `logs/classifier_health.log`.

## Dedupe

Regime change alerts are deduplicated by `dispatch_alert()` with `dedupe_scope="global"`. The health report is read-only and does not generate alerts — it's for operator inspection.

## No Additional Alerting Needed

The existing alert infrastructure covers:
1. **Regime changes** — via `_alert_regime_change()` in classifier
2. **Health monitoring** — via `classifier_health_check.py` cron
3. **Operator inspection** — via `run_regime_cron1_health.py`

No new Telegram alerting was added because the root cause was a write bug, not a missing alert. Now that writes work, the existing monitoring will detect any future staleness.
