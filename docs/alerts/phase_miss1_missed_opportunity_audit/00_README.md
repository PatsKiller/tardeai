# MISS-1 — Missed Opportunity and Alert SLA Audit

**Status:** COMPLETE

## Purpose

Tracks whether alerts arrive fast enough and whether proposals decay before
the operator can act. Uses DWSN as case study.

## Audit Results (last 7 days)

| Metric | Value |
|--------|-------|
| Proposals reviewed | 32 |
| Rebuild required | 8 |
| Missed (price moved) | 12 |
| SLA breaches | 1 |
| Alerts sent | 1 |
| Alerts missing | 31 |

Most proposals pre-date ALERT-1/Q-1 deployment — alerts were not yet active.

## DWSN Case Study

Classification: **Avoided bad trade**, not missed opportunity.
- R:R was 1.95 at creation (below 2.0 minimum)
- PROMOTE-1 would now prevent this proposal from being created
- Price moved 14% within 32 minutes
- System correctly blocked approval

## Scripts

- `missed_opportunity_policy.py` — Timing, decay, and classification
- `report_missed_opportunity_audit.py` — Full audit report
- `report_alert_sla_status.py` — Alert SLA tracking

## Tests

10/10 MISS-1 + ALERT-2 17/17 + Q-1 20/20 regression.
