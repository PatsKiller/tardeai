# Phase 6C Audit Schema Report

**Date:** 2026-05-15

## Tables Created

### paper_proposal_approval_audit

Primary audit table — one row per approval attempt.

| Column | Type | Purpose |
|--------|------|---------|
| id | BIGSERIAL | Primary key |
| created_at | TIMESTAMPTZ | Attempt timestamp |
| proposal_id | INTEGER | Which proposal |
| symbol | TEXT | Ticker |
| approval_status | TEXT | Final outcome (started, blocked_*, approved_*, error_*) |
| block_reason | TEXT | Why it was blocked |
| session_policy_json | JSONB | Session gate result |
| market_revalidation_json | JSONB | Market revalidation result |
| risk_gate_json | JSONB | Risk gate result |
| paper_trade_json | JSONB | Paper trade creation result |
| alpaca_response_json | JSONB | Alpaca submission result |
| gate_sequence | TEXT[] | Ordered list of gates attempted |
| passed_session_gate | BOOLEAN | Session gate passed? |
| passed_market_revalidation | BOOLEAN | Market revalidation passed? |
| passed_risk_gate | BOOLEAN | Risk gate passed? |
| paper_trade_created | BOOLEAN | Paper trade created? |
| alpaca_submitted | BOOLEAN | Alpaca order submitted? |
| alpaca_mode | TEXT | ALPACA_MODE at time of attempt |
| live_trading_enabled | BOOLEAN | Was live trading on? |

### paper_proposal_approval_audit_events

Granular event sub-table — multiple rows per audit attempt.

| Column | Type | Purpose |
|--------|------|---------|
| id | BIGSERIAL | Primary key |
| audit_id | BIGINT FK | Parent audit row |
| event_type | TEXT | Gate name or event |
| event_status | TEXT | passed/blocked/failed/ok |
| message | TEXT | Human-readable detail |
| event_json | JSONB | Event payload |

## Indexes

8 indexes on main table, 2 on events table.

## Safety

- Additive only — no existing tables altered
- Tables contain only paper proposal audit data
- No secrets, credentials, or PII stored
- IP/user-agent hashed (SHA-256)

## Rollback

```sql
DROP TABLE IF EXISTS paper_proposal_approval_audit_events;
DROP TABLE IF EXISTS paper_proposal_approval_audit;
```
