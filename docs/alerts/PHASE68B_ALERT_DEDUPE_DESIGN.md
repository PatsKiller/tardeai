# Phase 68B — Alert Dedupe Design

## Dedupe Key

`{alert_type}:{affected_component}:{root_cause_class}` within configurable time bucket (default: 60 minutes).

## Rules

1. Suppress repeated identical alerts within window
2. Send grouped summary instead of spam
3. Escalate if repeated AFTER a "fixed" status
4. Never suppress first CRITICAL alert
5. Never suppress "recovered" alert
6. Track suppression count for operator review
