# Stale Proposal Hygiene Result

**Date:** 2026-05-26  
**Commit:** 5fd70c5 (no code changes — DB-only operation)  

## Action Taken

Expired 51 stale paper_trade_proposals by setting `signal_decision='expired_stale'`:

| Batch | Count | Criteria |
|-------|-------|----------|
| >14 days, no open trade | 29 | Age expired, no linked position |
| 7-14 days, no open trade | 22 | Age expired, no linked position |
| **Total expired** | **51** | |

## Remaining (27 proposals)

| Category | Count | Action |
|----------|-------|--------|
| Linked to open trades | 13 | Kept — correct |
| Recent (4-6 days) | 14 | Kept — within normal pipeline window |

## Safety

- Proposals with open trade links: NEVER TOUCHED
- No orders placed
- No positions modified
- No stops changed
- ALPACA_MODE=paper, LLM_DISABLE=true

## Before/After

| Metric | Before | After |
|--------|--------|-------|
| Stale proposals | 78 | 27 |
| Expired | 0 | 51 |
| Linked to open trades | 13 | 13 (unchanged) |
