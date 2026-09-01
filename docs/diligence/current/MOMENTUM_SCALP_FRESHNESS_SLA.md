# Momentum Scalp Freshness SLA

Status:      ACTIVE
as_of:       2026-06-28T18:07:57-04:00
Measured at: efcc51365 / not measured

**Status: PASS** | window: 30d
_Generated: 2026-06-28T21:58:55.662063+00:00_
_Source: `python3 scripts/momentum_scalp_freshness_sla_report.py --days N --json`_

## Latency created → first ATM (49 proposals)

- median **9.94 min** · p95 **14.97 min** · max 226.12 min

## Failure breakdown

- **Stale-quote failures: 27** (median quote age at failure: 1070.0 min, freshness window 15.0 min)
- **TTL expiries: 0**

## Fast-path timing eligibility (deterministic validation fast-path, NO approval)

| If fast-path ran within | Would submit to paper | Missed by slow timing |
|------|------|------|
| within 1 min | 2 | 47 |
| within 3 min | 5 | 44 |
| within 5 min | 7 | 42 |

> Read-only SLA report. No broker writes. Stale-quote failures are an OPERATIONAL timing gap — the freshness gate is correct and must NOT be weakened. The fix is running the deterministic validation fast-path promptly (no human validation approval), not approving faster. Live trading is unchanged (operator confirmation + 2FA).

