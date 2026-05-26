# Post-A-4 Pipeline Observation — Day 1

**Date:** 2026-05-15 (Thursday)
**Commit:** 6ce832d
**Observer:** Claude Code + Operator

## Context

A-4 (commit `79ffb31`) fixed a systemic proposal pipeline defect where `--skip-auto-proposals` was set on all orchestrator runs and the incubator promoter wasn't reaching activated strategies. Commit `6ce832d` then fixed three follow-up bugs: morning brief render crash, paper account zeros, and missing newly-activated endpoint.

## Defects Fixed

| # | Issue | Root Cause | Fix |
|---|-------|-----------|-----|
| 1 | No proposals during market hours | `--skip-auto-proposals` on all runs | Removed flag (A-4) |
| 2 | Morning brief render crash | `parseUrgency()` on null `due` field | Null guard (6ce832d) |
| 3 | Paper account showing $0 | `api_v2.py` used `os.getenv()` without dotenv | Read from .env file (6ce832d) |
| 4 | Missing newly-activated endpoint | Specified in A-2 but never wired | Added endpoint (6ce832d) |

## Proposal Evidence (Day 1)

| Hour (ET) | Strategy | Symbol | Status |
|-----------|----------|--------|--------|
| 08:00 | gap_and_go | DRTS | REJECTED (RSI gate) |
| 09:00 | screener | FLYW | REJECTED (stop breached) |
| 10:00 | swing_trade | DRTS | PENDING |
| 11:00 | speculative_growth | INFU | PENDING |

**4 proposals in 4 hours** — hourly generation is working. Pre-A-4 there were near-zero daytime proposals.

## Scan Signal Evidence

| Hour (ET) | Signals | Unique Symbols |
|-----------|---------|----------------|
| 04:00 | 3 | 3 |
| 05:00 | 2 | 2 |
| 06:00 | 1 | 1 |
| 08:00 | 2 | 2 |
| 09:00 | 8 | 8 |
| 10:00 | 3 | 3 |

**19 signals across 6 hours** — scanner is finding candidates throughout the day.

## Activated Strategy Status

| Strategy | Defect Fixed | Proposals Since Activation | Trades |
|----------|-------------|---------------------------|--------|
| speculative_growth | Expired unsubmitted | **1** | 0 |
| recovery_watch | Rejected low approval | 0 | 0 |
| sector_rotation | Expired unsubmitted | 0 | 0 |
| fib_retracement_bounce | Not in strategy groups | 0 | 0 |
| earnings_post_momentum | Not in strategy groups | 0 | 0 |

1 of 5 activated strategies has produced a proposal. The others are WAITING — this is expected on Day 1 since they need matching scan signals.

## System Health

| Check | Result |
|-------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| Holdings | $1,190,634 |
| Paper account equity | ~$100,070 |
| Phase 6 tests | 83/83 pass |
| Morning brief | Renders correctly |
| Newly-activated endpoint | Returns 5 strategies |

## A-5 Readiness

**NOT READY YET**

A-5 requires:
- 3-5 trading days of post-A-4 evidence
- Proposals from 3+ strategies (currently 3: gap_and_go, screener, swing_trade + 1 activated)
- No repeat pipeline defects
- Phase 6 gates remaining clean
- Morning brief stable
- Newly-activated endpoint stable

## A-3 Readiness

**DEFERRED** — Morning brief automation (A-3.5 commit `1db185f`) is running but needs multi-day stability proof.

## Observation Window

| Item | Date |
|------|------|
| Observation started | 2026-05-15 |
| Minimum observation end | 2026-05-20 (3 trading days) |
| Recommended observation end | 2026-05-22 (5 trading days) |
| Next check | 2026-05-16 (Friday — check if proposals continue) |
