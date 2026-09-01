# PHASE 190G — PENDING_TRADING_WINDOW Lifecycle Report

Status:      HISTORICAL
as_of:       2026-06-02T10:33:34-04:00
Measured at: efcc51365 / not measured

**Scope:** DESIGN + safe advisory analyzer. **No GO/WAIT/NO-GO logic changed** (hard constraint).
**File:** `scripts/pending_trading_window.py` (advisory, dry-run; no status mutation).

---

## Problem (from 189B)
There is no deferred-to-open lifecycle state. A premarket scalp (e.g. ELMT) loops through
`should_delay_execution → "premarket_wait_for_open"` every 15-min cycle, re-deriving "delayed"
from scratch, and eventually auto-rejects on age (`auto_blocked_230min`) rather than being parked
until the open. Dedup prevents duplicate rows, but the proposal still churns.

## Designed lifecycle (to implement under a later approval gate)
```
PENDING ──(generated outside valid window)──▶ PENDING_TRADING_WINDOW
   ▲                                              │
   │                                              │ first valid trading window + fresh quote
   └──────────────(window opens)─────────────────┘
PENDING_TRADING_WINDOW ──(stale quote at open)──▶ HELD_STALE
PENDING_TRADING_WINDOW ──(window + fresh + eligible)──▶ (hand to existing auto-approver, unchanged)
PENDING_TRADING_WINDOW ──(aged past max_window_age)──▶ EXPIRED (reason=window_never_opened)
```
Rules:
- **Park, don't loop:** when `should_delay_execution()` is true at generation, set
  `PENDING_TRADING_WINDOW` instead of leaving `PENDING` to be re-revalidated each cycle.
- **Single parked row per (symbol, strategy):** reuse existing dedup; new generations refresh the
  parked row rather than creating churn.
- **Revalidate once at first valid window:** on session open, run the normal freshness/eligibility
  checks **once**; if stale → `HELD_STALE` (with reason); if fresh+eligible → hand to the existing
  auto-approver **without changing its GO/WAIT logic**.
- **ELMT:** would be parked premarket and revalidated at 09:30 instead of auto-rejecting on age.

## Safe analyzer shipped now (`pending_trading_window.py`)
Advisory/dry-run: reports which active proposals **would** be parked and any duplicate
(symbol,strategy) groups — **mutates nothing**. Runtime (09:21 ET, session=regular): 1 active
proposal, 0 would-park (correct — regular session), 0 duplicate groups.

## Why implementation is gated, not done here
Wiring a new status into proposal generation + the revalidation/approver hand-off touches the
approval path, which is adjacent to GO/WAIT. Per this phase's constraint, that wiring is deferred
to an explicit operator-approved step (proposed **Phase 191**). The analyzer + design are the safe
deliverables now.
