# Automated Trading Live Path Audit Report — 2026-05-29

## Status: WORKING CORRECTLY — No Eligible Non-Intraday Proposals Currently Pending

## Findings

| Item | Value |
|------|-------|
| Automated trading status | **Working — correctly blocked** |
| ATM mode | **active** |
| Live trading enabled | NO (ALPACA_MODE=paper, LLM_DISABLE=true) |
| Eligible proposals | 0 (none pending) |
| Blocked proposals (24h) | 9 (6 not-enriched, 3 intraday-skip) |
| Approved-not-submitted | 0 |
| Latest proposal | 2026-05-29 14:16 |
| Latest paper trade | 2026-05-28 11:03 (ONDS/SNOW) |
| Dry-run/freeze active | **NO** — ATM is active |
| Submitter last run | N/A (no pending submissions) |

## Root Cause
16/20 recent proposals are `momentum_scalp` — on the `same_day_skip_strategies` list because ATM's 15-min cadence is too slow for intraday execution. The 2 non-intraday proposals (SNOW, ONDS) were successfully approved and created paper trades.

## Top Block Reasons
| Gate | Count |
|------|-------|
| not_yet_enriched | 6 |
| same_day_strategy_atm_cadence_too_slow | 3 |

## Execution Readiness Endpoint Added
- `GET /api/v2/atm/execution-readiness` — read-only diagnostic
- Returns: ATM mode, pending count, block reasons, latest times, can_submit_now flag
- File: `scripts/api_v2.py`

## Safety Confirmation
| Check | Result |
|-------|--------|
| Orders placed | NO |
| Broker writes | NO |
| Proposal mutations | NO |
| paper_trades mutations | NO |
| Journal mutations | NO |
| DB writes | NO (read-only endpoint only) |
| Cron changes | NO |
| LLM calls | NO |

## Recommended Next Action
No fix needed — system is working as designed. If more automated trades are desired, either:
1. Generate more non-intraday proposals (swing/earnings/income strategies)
2. Build faster intraday execution path
3. Manually approve intraday proposals via Telegram
