# ATM Burn-in Day 1 — Deferral Report

Status:      ACTIVE
as_of:       2026-05-22T19:21:56-04:00
Measured at: efcc51365 / not measured

**Attempted:** 2026-05-22 22:57 ET (Friday)
**Result:** DEFERRED to Monday 2026-05-26

## Deferral Reasons

| # | Condition | Status | Limit | Verdict |
|---|-----------|--------|-------|---------|
| 1 | Market hours | CLOSED (22:57 ET) | 09:35–15:30 | BLOCKED |
| 2 | Daily ATM entries | 4 used | 1/day | BLOCKED |
| 3 | Concurrent ATM positions | 2 open | 2 max | AT CAP |

## Safety Conclusion

- Orders created after deferral: **0**
- Trades created after deferral: **0**
- Approvals created after deferral: **0**
- ATM decisions after deferral: **0**
- ATM final mode: **dry_run**
- Stop reconciliation: **5/5 RECONCILED, 0 critical**
- Weekend safety: ATM frozen, stops protected, no active cycles will fire

## Monday Retry

- **Window:** Monday 2026-05-26 after 09:35 ET
- Daily counter resets at midnight → 0 entries used
- Concurrent positions may change over weekend (stops/targets)
- Re-run preflight before enabling active mode

## B-1 Observation Decision

- **Decision:** Leave B-1 exclusion until auto-expiry (2026-05-25)
- **Do NOT remove early**
- On Monday, verify B-1 has expired before burn-in
- B-1 expiry allows bucket2 strategies to flow through ATM gates again
- B-1 expiry does NOT auto-approve — all ATM gates still apply
- `same_day_skip` still excludes momentum_scalp and gap_and_go
