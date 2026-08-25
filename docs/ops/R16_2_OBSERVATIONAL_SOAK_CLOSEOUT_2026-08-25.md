# R16.2 — Observational soak closeout

**Date:** 2026-08-25  
**Authority:** READ_ONLY_ADVISORY · `MEMORY_BEHAVIOR_INFLUENCE=0`  
**Maturity:** 88 (unchanged)  
**R17:** not started · **wiring:** not added

## Pins

| | SHA |
|---|---|
| repository_head | `eff5aa63400cec68d96d7a518406b318513ee18f` (#512 docs) |
| runtime_source / CURRENT | `55520666b4a742b9ed893c3231b414d089312363` |
| exact release | `55520666-main-exact-phase2-20260825-125124` |

Docs-on-main vs runtime is expected. No redeploy. No #505 merge. Canary unset. Cash `POLICY_GAP`.

## What R16.2 did

Collect natural evidence. Freeze the R17 gap register. **No new learning-loop hooks.**

- 11 timer-fired material scans on `55520666` (12:58–14:39 EDT), none started by hand
- 25 unique live `decision_id`s; **auto checkpoint registration = 0**
- Durable scheduler still 18 checkpoints / 25 historical observations (R16.1 operator persist)
- Earliest dated `due_at` = **2026-08-26T17:03:10Z** — none genuinely due; none marked due; no fabricated time
- In-memory due processor on a not-yet-due row → `OUTCOME_PENDING_DATA`, **not persisted**
- Restart: checkpoint/observation jsonl SHA256 unchanged
- Latest 18:39Z scan: HOLD_CASH / WAIT / TRIM SCHD all `checkpoint_created=false`; SCHD joined to canonical TRS guid; cash/wait unresolved (not minted)
- Second free-first on pin at 18:27:09Z: 120 FRESH_NO_CHANGE, paid=0
- Promotion ceiling still `REVIEW_READY`; registries byte-identical

## Why 89 is still not awarded

A. New material decisions do **not** enter the durable observational lifecycle automatically.  
B. No genuinely elapsed natural checkpoint has completed end-to-end.

R16.2 did not implement that wiring. That is the point of the soak.

## R17 (later, surgical)

See `docs/_evidence/r16_2/R17_GAP_REGISTER.json`. First job:

`natural material decision → idempotent durable outcome checkpoint → due processor → OutcomeObservation → calibration/learning cockpit`

Must also handle `unchanged_replay` decision_id churn (G4) so auto-register does not spam checkpoints.

**90 remains blocked** on NATURAL_LONGITUDINAL improvement.
