# Momentum Scalp Freshness SLA

**Status: PASS** | window: 30d  
_Generated: 2026-06-28T17:01:13.778113+00:00_  
_Source: `python3 scripts/momentum_scalp_freshness_sla_report.py --days N --json`_  

## Latency created → first ATM (50 proposals)

- median **9.94 min** · p95 **14.97 min** · max 226.12 min

## Failure breakdown

- **Stale-quote failures: 27** (median quote age at failure: 1070.0 min, freshness window 15.0 min)
- **TTL expiries: 0**

## ATM cadence eligibility

| If ATM ran within | Eligible | Missed by slower cadence |
|------|------|------|
| within 1 min | 2 | 48 |
| within 3 min | 5 | 45 |
| within 5 min | 7 | 43 |

> Read-only SLA report. No broker writes. Stale-quote failures are an OPERATIONAL timing gap — the freshness gate is correct and must not be weakened.

