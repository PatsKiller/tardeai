# Phase 68B — Alert Dedupe Design

Status:      HISTORICAL
as_of:       2026-06-01T11:52:54-04:00
Measured at: efcc51365 / not measured

## Dedupe Key

`{alert_type}:{affected_component}:{root_cause_class}` within configurable time bucket (default: 60 minutes).

## Rules

1. Suppress repeated identical alerts within window
2. Send grouped summary instead of spam
3. Escalate if repeated AFTER a "fixed" status
4. Never suppress first CRITICAL alert
5. Never suppress "recovered" alert
6. Track suppression count for operator review
