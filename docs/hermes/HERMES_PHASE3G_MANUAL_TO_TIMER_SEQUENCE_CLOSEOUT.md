# Hermes Phase 3G — Manual-to-Timer Sequence Closeout

**Date:** 2026-05-31
**Status:** ALL PHASES COMPLETE

---

## Phase Summary

| Phase | Status | Commit | Key Result |
|-------|--------|--------|------------|
| 3B | COMPLETE | fa2c730 | Manual dry-run loop: 3/3 validated, kill switch PASS, zero DB writes |
| 3C | COMPLETE | 42597a7 | Manual apply: 2/3 staged (FJSCX id=8, TELO id=9), 1 timeout |
| 3D | COMPLETE | a36779d | Dashboard monitoring: kill switch + auto loop status added |
| 3E | COMPLETE | 2adb06c | Timer/service drafts finalized, NOT installed |
| 3F | COMPLETE | 31e1481 | Timer activated (dry-run mode only), manual trigger PASS |
| 3G | COMPLETE | (this) | Closeout and readiness review |

---

## Current State

| Metric | Value |
|--------|-------|
| Hermes research rows | 9 (7 prior + 2 from Phase 3C) |
| Hermes embeddings | 7 (from Phase 2) |
| Timer | Active (daily 01:00 UTC, dry-run mode) |
| Service mode | DRY-RUN (no --apply) |
| Gateway | Active (systemd, auto-restart) |
| Kill switch | Not active |
| Dashboard | Live with monitoring |
| Production | 38 trades, 145 proposals (UNCHANGED) |

## Safety Across All Phases

| Item | 3B | 3C | 3D | 3E | 3F |
|------|----|----|----|----|-----|
| DB writes | 0 | 2 | 0 | 0 | 0 |
| Embeddings | 0 | 0 | 0 | 0 | 0 |
| Dashboard | — | — | read-only | — | — |
| Timer/service | 0 | 0 | 0 | 0 | dry-run timer |
| Broker | 0 | 0 | 0 | 0 | 0 |
| Production | 0 | 0 | 0 | 0 | 0 |

## Rollback Files

| File | Scope |
|------|-------|
| HERMES_PHASE3C_ROLLBACK.sql | Phase 3C rows (ids 8, 9) |
| HERMES_PHASE3F_TIMER_DISABLE_ROLLBACK.md | Timer disable commands |

---

## Next Recommended Gate

**Phase 3H — enable apply-mode autonomous loop (requires separate approval)**

Before enabling apply mode:
1. Verify dry-run timer has run successfully for 1+ scheduled cycles
2. Review dry-run output quality
3. Confirm row caps and kill switch work in scheduled context
4. Operator explicitly approves changing service to `--apply` mode
