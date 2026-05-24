# Phase 6D Preflight — Proposal Stale-Time Sweeper

**Date:** 2026-05-15
**Phase:** 6D

## Safety Checks

| Check | Result |
|-------|--------|
| ALPACA_MODE | **paper** |
| LLM_DISABLE_LIVE_EXECUTION | **true** |
| Holdings guard ($1M+) | **OK: $1,191,941** |
| Phase 6A/6B/6C | **ALL PRESENT** |

## Current Proposal State

| Status | Count |
|--------|-------|
| EXPIRED | 38 |
| REJECTED | 22 |
| RISK_BLOCKED | 2 |
| expired (lowercase) | 1 |
| PENDING | 1 |

Only 1 PENDING proposal: DRTS swing_trade, 5 min old, expires 2026-05-20.

## Existing Freshness Infrastructure

The `paper_trade_proposals` table already has:
- `expires_at` — strategy-aware expiry timestamp
- `lifecycle_status` — ACTIVE/EXPIRED/etc.
- `action_state` — BLOCKED/PAPER_READY/NEEDS_REVIEW
- `proposal_timeframe_class` — intraday/short_swing/position
- `created_at` — proposal creation timestamp

Existing expiry mechanism in `cleanup_stale_proposals.py` handles >24h, blocked >4h, missing data >48h.

## Preflight Verdict

**PASS** — Proceeding. Will build staleness policy on top of existing `expires_at` and add freshness gate to approval.
