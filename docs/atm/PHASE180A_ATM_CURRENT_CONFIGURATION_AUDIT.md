# Phase 180A: ATM Current Configuration Audit

Status:      HISTORICAL
as_of:       2026-06-01T23:26:38-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Mode**: PAPER ONLY — Level 7 PROHIBITED

## ATM State

| Setting | Value |
|---------|-------|
| ATM Mode | `active` |
| Paused Until | NULL |
| Last State Change | 2026-05-22 19:14:15 UTC |
| Changed By | john-approved |
| Last Evaluated | 2026-06-01 15:45:02 UTC |
| Config Hash | `81f73c470b9b` |
| Daily Loss Pause Armed | true |

## Account Configuration

| Setting | Value |
|---------|-------|
| Account | alpaca_paper (ONLY) |
| Account Size | $100,000 |
| ALPACA_MODE | `paper` |
| ENABLE_ALPACA_PAPER | `true` |
| LIVE_TRADING_ENABLED | NOT SET (defaults false) |
| LLM_DISABLE_LIVE_EXECUTION | `true` |
| Paper Endpoint | https://paper-api.alpaca.markets |
| Live Endpoint | BLOCKED (adapter rejects non-paper URLs) |

## Position Limits

| Setting | Value | Source |
|---------|-------|--------|
| Max concurrent positions | 6 | atm_config.yaml |
| Max new trades per day | 3 | atm_config.yaml |
| Max % of account per trade | 10% ($10K) | atm_config.yaml |
| Max % per strategy | 25% ($25K) | atm_config.yaml |
| Max % per sector | 35% ($35K) | atm_config.yaml |
| Max shares per trade | 2,000 | alpaca_paper_adapter.py |

## Risk Controls

| Setting | Value | Source |
|---------|-------|--------|
| Daily loss hard pause (per-account) | 0.25% ($250) | atm_config.yaml |
| Daily loss hard pause (aggregate) | 10% ($10K) | atm_config.yaml |
| Heat limit % | 6% | .env |
| Position concentration % | 8% | .env |
| Sector concentration % | 25% | .env |
| Correlation cap | 0.7 | .env |
| Manual kill switch only | true | atm_config.yaml |

## Stop/Target Logic

| Rule | Condition | Action |
|------|-----------|--------|
| R >= 1.0 | Breakeven | Move stop to entry |
| R >= 1.5 | Lock 0.5R | Move stop to 0.5R profit |
| R >= 2.0 | Lock 1.0R | Move stop to 1.0R profit |
| R >= 3.0 | Lock 2.0R | Tight trail |
| Near target (80%) | Tighten | Stop to lock 65% of target move |
| Target hit | Close | Market sell, log close_target |

## Operating Hours

| Setting | Value |
|---------|-------|
| Start ET | 07:00 |
| Stop new entries ET | 15:30 |
| Premarket execution | NO |
| After-hours execution | NO |
| ATM evaluation frequency | Every 15 minutes |

## Strategy Rules

| Rule | Value |
|------|-------|
| Same-day skip | momentum_scalp, gap_and_go |
| Classifier health threshold | 0.0 (disabled, cold start) |
| Strategy whitelist | EMPTY (all allowed) |
| Strategy blacklist | EMPTY (none blocked) |
| B-1 observation | Ended 2026-05-25 |

## Kill Switch / Emergency Stop

| Mechanism | Status |
|-----------|--------|
| ATM mode=paused | Available (`--set-mode paused`) |
| Daily loss auto-pause | DISABLED (manual_kill_switch_only=true) |
| Per-account loss threshold | 0.25% configured but manual-only |
| Aggregate loss threshold | 10% configured but manual-only |
| HIGH_LLM_SCHEDULER_DISABLED file | data/state/ directory |

## Submission Safety Gates (11 gates)

1. Already executed check
2. Live trading block (ALPACA_MODE must be paper)
3. Proposal status validation
4. Risk gate approval required
5. Trade plan validation (entry/stop/shares)
6. Duplicate open trade check
7. Duplicate active order check
8. Quality review rejection gate
9. Intel readiness check (warning)
10. Technical snapshot check (warning)
11. Paper validation requirement (warning)

## Stop Loss Quality Guards

- stop >= entry: BLOCKED
- stop > entry * 0.995: WARNED (< 0.5% gap)
- stop > target: BLOCKED (inverted)

## Current Activity

| Metric | Value |
|--------|-------|
| ATM decisions logged | 168 |
| Close actions | 4 |
| Overdue decisions | 12 |
| Pending proposals | 0 |
| Paper trades opened | 44 |
| Paper trades closed | 24 |
