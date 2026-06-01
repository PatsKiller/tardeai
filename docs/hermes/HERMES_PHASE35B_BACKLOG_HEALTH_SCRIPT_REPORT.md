# Hermes Phase 35B — Backlog Health Script Report

**Date:** 2026-06-01
**Status:** COMPLETE — manual run successful

## Script

- Path: `scripts/hermes_backlog_health_check.py`
- Manual run result: 10 backlog items analyzed

## Results

| Metric | Value |
|--------|-------|
| Total backlog | 10 |
| Open (staged) | 10 |
| High priority | 2 |
| Stale (>7 days) | 0 |
| Duplicate risks | 1 (id=27 vs id=25, both backtest_contradiction NULL symbol) |
| Missing owner_agent | 0 |
| Source surfaces | backtest(3), catalyst(1), journal(1), unknown(5) |

## Top Operator Review Items

1. [high] id=25 — momentum_scalp 30% win rate
2. [high] id=26 — all_signals 33.9% win rate
3. [medium] id=19 — Income-rotation research
4. [medium] id=20 — TELO thesis strengthen/reject
5. [medium] id=23 — Telegram actionability standard

## Safety

- [x] DB writes: ZERO
- [x] Status changes: ZERO
- [x] Alerts: ZERO
- [x] File output only
