# ATM v1 — Day 1 Dashboard Audit + Fixes

**Date:** 2026-05-22
**Session:** Dashboard polish for operator trust before ACTIVE flip

## Issues Fixed

### Issue 1 (HIGH): Classifier health shows null for every strategy
**Root cause:** `get_health()` returns 0.0 when < 3 closed trades. Frontend showed `—` for 0 values.
**Fix:**
- `atm_classifier_health.py`: New `get_health_detail()` returns score, closed_trades, has_baseline, wins, avg_r
- API `/api/v2/atm/strategy-health`: Returns enriched data with baseline info
- Frontend: Shows "0.00 (no baseline)" with trade count instead of `—`
- Footer note explains cold-start state and how to unblock
**Commits:** `18046ee`, `c50a1b1`, `fdbf0e0`

### Issue 2 (HIGH): Queue preview doesn't show predicted_decision
**Root cause:** Queue preview only showed raw proposal data with no gate predictions.
**Fix:** `/api/v2/atm/queue-preview` now runs each proposal through the same gate chain
(account check → B-1 → same-day skip → classifier health) without committing.
Returns `predicted_decision` (would_approve/would_reject/would_defer) and `predicted_reason`.
Frontend shows color-coded prediction chips.
**Commit:** `c50a1b1`, `fdbf0e0`

### Issue 3 (MEDIUM): config_hash shows "none" on atm_state
**Root cause:** `atm_state.config_hash` was only updated by `save_config()`, never by the auto-approver cycle.
**Fix:** Auto-approver heartbeat now writes current config hash to `atm_state` on every tick.
Also seeded current hash (`e0671b4e944f`) directly.
**Commit:** `39070c1`

### Issue 4 (MEDIUM): STALE warning fires after-hours
**Root cause:** Frontend showed STALE when `lastEvalAge > 20` regardless of market hours.
**Fix:** API now returns `is_market_hours` and `next_expected_cycle`. Frontend only shows
STALE warning during market hours. After-hours shows "(market closed, next: Mon 09:35 ET)".
**Commit:** `c50a1b1`, `fdbf0e0`

### Issue 5 (MEDIUM): Per-account card mixes ATM and manual positions
**Root cause:** `new_today` count included both ATM and manual trades.
**Fix:** API returns `new_today_atm` (trades with `atm_decision_id IS NOT NULL`).
Frontend shows "New today: 2 (ATM: 0 · manual: 2)".
**Commit:** `c50a1b1`, `fdbf0e0`

### Issue 6 (LOW): Ghost cards for disabled accounts
**Fix:** Disabled accounts now render as ghost cards with dashed border and "Disabled" label.
**Commit:** `fdbf0e0`

### Issue 7 (NEW): Quote status banner contradicts per-card status
**Root cause:** The banner's `UNKNOWN_QUOTE` check used `last_price_checked_at` and
`execution_readiness` fields independently, while the per-card display used
`classify_quote_trust()` from `proposal_quote_trust.py`. A proposal with
`last_price_checked_at` set but no `execution_readiness` would show "0 unknown"
in the banner but "NOT_CHECKED" on the card.
**Fix:** Banner now uses the already-computed `trust_audit.quote_trust.quote_trust_status`
from `classify_quote_trust()` for both UNKNOWN_QUOTE and STALE_QUOTE verdicts.
Both banner counts and per-card status now derive from the same source.
**Commit:** `e41fcda`

## Telemetry Snapshot

### ATM Decisions (10:00 ET cycle — after classifier_health fix)
```
ARM    core_growth_compounder     dry_run_approved
NWG    dividend_growth_compounder dry_run_approved
NVDA   dividend_growth_compounder dry_run_approved
AGNC   reit_income                dry_run_approved
BCS    dividend_growth_compounder dry_run_approved
CMCSA  dividend_growth_compounder dry_run_approved
SHMD   swing_trade                deferred (B-1 bucket2)
MUD    recovery_watch             deferred (B-1 bucket2)
```

### Top Blockers (last 24h)
```
classifier_health:              6 (from 09:45 cycle, before fix)
bucket2_b1_observation_active:  4 (B-1 observation until 2026-05-25)
```

### Classifier Health Coverage (30-day closed trades)
```
Strategy                    Closed  Wins  Baseline?
swing_breakout              2       2     No (need 3+)
momentum_scalp              2       0     No
earnings_catalyst           2       1     No
dividend_growth_compounder  1       1     No
swing_trade                 1       0     No
```

No strategy has baseline yet. All show "0.00 (no baseline)" on dashboard.
With `min_classifier_health: 0.0` (from supply triage), ATM approves in dry_run.

### Current Supply
- 17 proposals in last 24h
- 8 currently PENDING
- 6 dry_run_approved at 10:00 cycle
- 2 deferred (B-1 bucket2)

## Recommendation

**Do NOT flip to ACTIVE yet.** Reasons:
1. No strategy has classifier health baseline (0 of 6 strategies have 3+ closed trades)
2. B-1 observation window active until 2026-05-25 (blocks 5 strategies)
3. `min_classifier_health` is temporarily at 0.0 — needs restoration to 0.50
4. ATM has only run 2 cycles in dry_run — need more data

**Flip conditions:**
- 3+ strategies accumulate 3+ closed trades (health > 0)
- B-1 observation expires (2026-05-25)
- Restore `min_classifier_health` to 0.50
- 2-3 days of clean dry_run operation showing correct approve/reject patterns

## Safety Verification
- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true
- Holdings: $1,201,659 / 47 positions (unchanged)
- No hardcoded broker names in changed files
- All proposals remain PENDING — no live execution
