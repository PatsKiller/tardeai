# Why Automated Trading Is Not Progressing — 2026-05-29

## Classification: A + B — Working Correctly, Correctly Blocked

Automated trading IS working. The pipeline is running, ATM is active, and proposals are being generated, evaluated, and decided. The reason it appears "not working" is:

### Root Cause 1: Most proposals are intraday strategies on the same-day skip list
- **16 of 20 recent proposals** are `momentum_scalp`
- **2 of 20** are `gap_and_go`
- Both `momentum_scalp` and `gap_and_go` are on `same_day_skip_strategies` in `config/atm_config.yaml`
- ATM runs every 15 minutes — too slow for intraday strategies that need sub-minute execution
- These are **correctly rejected** with reason `same_day_strategy_atm_cadence_too_slow`
- Operator can still manually approve via Telegram

### Root Cause 2: Non-intraday proposals DO get approved and create trades
- SNOW (#138, fib_retracement_bounce) — APPROVED_FOR_PAPER_TEST, paper_trade created
- ONDS (#139, swing_breakout) — APPROVED_FOR_PAPER_TEST, paper_trade created
- BLMN (#130, swing_trade) — earlier approval, paper_trade exists

### Root Cause 3: Pre-market proposals deferred due to missing enrichment
- 6 proposals created at 4:06 AM were correctly deferred by ATM at 7:00 AM with `not_yet_enriched`
- They were later expired at 10:29 AM (intraday > 8h threshold)
- This is the correct health-agent flow: defer until enriched, expire if not enriched in time

## Current State
| Metric | Value |
|--------|-------|
| ATM mode | **active** |
| Pending proposals | **0** |
| Approved not submitted | **0** |
| Latest proposal | 2026-05-29 14:16 |
| Latest paper trade | 2026-05-28 11:03 |
| Last ATM evaluation | 2026-05-29 14:45 |
| Last enrichment | 2026-05-29 14:50 |
| Dry-run/freeze | **NO** |
| Submitter running | N/A (no pending submissions) |

## Top Block Reasons (last 24h)
| Gate | Count | Meaning |
|------|-------|---------|
| not_yet_enriched | 6 | Pre-market proposals deferred until enrichment |
| same_day_strategy_atm_cadence_too_slow | 3 | Intraday strategies correctly skipped by ATM |

## Why It Looks Broken
1. The proposal generator is producing mostly intraday (momentum_scalp) proposals
2. ATM correctly rejects intraday proposals because 15-min cadence is too slow
3. All non-intraday proposals that met criteria were approved and traded
4. No proposals are currently PENDING — all have been resolved

## What Would Fix the Appearance
- **Option A**: Generate more non-intraday proposals (swing, earnings, income strategies)
- **Option B**: Build a faster intraday execution path (sub-minute, not 15-min ATM)
- **Option C**: Manually approve momentum_scalp proposals via Telegram during market hours
- **Option D**: No fix needed — system is working as designed

## Is Anything Broken?
**NO.** The system is working correctly. ATM is active, evaluating proposals every 15 minutes, correctly skipping intraday strategies, and approving eligible non-intraday proposals when they appear.
