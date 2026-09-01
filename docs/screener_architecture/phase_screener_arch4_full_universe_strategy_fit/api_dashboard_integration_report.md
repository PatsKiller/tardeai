# SCREENER-ARCH-4 — API/Dashboard Integration

Status:      ACTIVE
as_of:       2026-05-19T16:51:15-04:00
Measured at: efcc51365 / not measured

## API Endpoint

### GET /api/v2/strategy-fit/summary

Read-only. Returns latest audit run summary with:
- audit_run_id
- symbols/strategies/evaluations counted
- match_strength distribution
- recommendation distribution
- top match strategy distribution

## Dashboard

UI integration deferred — API only this phase. Dashboard card can be added to Paper Governance in a future phase.

## Rules
- Read-only, no mutations
- No proposals, trades, or orders
- No secrets
