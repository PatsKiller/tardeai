# PROMOTE-1 — Pre-Promotion Readiness Gate

**Status:** COMPLETE

## Problem

DWSN was promoted to a paper proposal with entry $3.91 but within 30 minutes:
- Price moved to $4.46 (14% drift)
- Spread widened to 14.8%
- Volume only 1,873 (below 100K minimum)
- R:R 1.95 below 2.0 minimum
- Technical, strategy fit, catalyst quality, backtest, and LLM analysis all missing

The system promoted a candidate that was not ready for operator action.

## Root Cause

Neither incubator_proposal_promoter nor auto_proposal_generator checked R:R,
price drift, spread, volume, or evidence completeness before INSERT.

## Fix

Created `pre_promotion_readiness_policy.py` with checks for:
- R:R minimum (2.0)
- Price drift maximum (8%)
- Spread maximum (per strategy family)
- Valid YAML-backed strategy_id
- Out-of-scope daily scalp source

Wired into both proposal creation paths:
- `incubator_proposal_promoter.py` — blocks promotion if readiness fails
- `auto_proposal_generator.py` — returns None if readiness fails

## DWSN Under New Policy

DWSN would be **BLOCKED** by pre-promotion gate:
- R:R 1.95 < 2.0 minimum
- Candidate kept in incubator until R:R improves or entry/target adjusts

## Tests

15/15 PROMOTE-1 + Q-1 20/20 + SP-2C 17/17 regression.
