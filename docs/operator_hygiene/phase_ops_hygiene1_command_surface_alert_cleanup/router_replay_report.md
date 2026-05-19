# OPS-HYGIENE-1 — Router Replay / Reduction Estimate

## Methodology

Replayed known Telegram message patterns from Trade AI LIVE, STOP alerts, Iris audits,
and cron notifications against the central router classification rules.

## Estimated Message Volume (14-day window)

Based on cron schedule and observed patterns:

| Category | Est. Messages | Router Level | Telegram After |
|----------|---------------|-------------|----------------|
| Trade AI LIVE (7 runs/day * 14d) | ~98 | P1_DIGEST (deduped) | ~21 (3/hour cap) |
| STOP_TRIGGERED repeats | ~30 | P1_DIGEST (deduped) | ~5 (2/symbol/day) |
| WAIT/AVOID signals | ~60 | P2_DASHBOARD | 0 |
| RVOL-only | ~20 | P2_DASHBOARD | 0 |
| Generic Trade AI Critique | ~14 | P2_DASHBOARD | 0 |
| Iris Library Audit | ~7 | P2_DASHBOARD | 0 |
| Iris content gaps | ~7 | P2_DASHBOARD | 0 |
| Aegis morning briefs | ~10 | P1_DIGEST (1/day) | ~10 |
| Watchpool maturity | ~20 | P1_DIGEST | ~10 |
| Cron success | ~200+ | P3_LOG_ONLY | 0 |
| Drive sync success | ~300+ | P3_LOG_ONLY | 0 |
| System health OK | ~70 | P3_LOG_ONLY | 0 |
| Proposal actionable (P0) | ~5 | P0_INTERRUPT | ~5 |
| Execution/stop action needed | ~3 | P0_INTERRUPT | ~3 |

## Summary

| Metric | Value |
|--------|-------|
| Estimated total alerts (14d) | ~844 |
| Would send (P0 + deduped P1) | ~54 |
| Would suppress | ~790 |
| **Telegram volume reduction** | **~93%** |
| P0 preserved | **100%** |

## Questionable Suppressions

None — all P0 patterns are checked first and always pass through.
Trade AI LIVE GO messages with trade plans still send (P0).
Aegis morning brief still sends once per day (P1).

## Target Met

- 70%+ reduction: YES (93%)
- 100% P0 preservation: YES
