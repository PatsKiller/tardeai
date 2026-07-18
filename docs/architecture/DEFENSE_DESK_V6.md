# Defense Desk v6 — The Core Registry · Funded Rotation Pairs · Ladders You Can Read (2026-07-18)

Session 6. The disconnected voices connect: trims now FUND rotate-ins in one card,
the operator owns a ★CORE registry the engines enforce, and ladders read at arm's
length. **The operator confirmed the core seed live mid-session (12 holdings)** —
C3 semantics activated on real data the same hour.

## WS-CORE — the operator-owned ★CORE registry
- `operator_core_registry` (+`_meta`) — deliberately DISTINCT from the `core_holding`
  strategy enum. GET `/defense/core` (rows + one-time seed proposal: ≥$25K positions
  + SCHD/JEPI/JEPQ income sleeve, pre-checked); POST `/defense/core/{toggle,confirm}`.
  After seed confirmation ONLY operator toggles write — the system never
  auto-designates.
- **C3 enforced in the engine, tested:** core cards render ★CORE TRIM with full-exit
  language BANNED (verified absent), trim fraction capped at config 60%, cleanup
  NEVER touches core regardless of size (live: cleanup shrank 11→9 when SCHG's
  residuals became core), re-entry watches get the patient 90-session window (vs 60),
  core rollback-open rows rank first.
- UI: seed-confirm modal in the stance strip (operator confirmed 12 live), per-chip
  gold ★ toggle with toast + instant persistence (proven across reload, test rows
  reverted). **Flag: Portfolio HoldingsCard is the LOCKED Card v4 family — the
  checkbox was NOT added there per the operator's own lock; operator decision
  pending on whether to amend the lock.**

## WS-PAIR — funded rotation pairs (`scripts/defense_rotation_pairs.py`)
- `build_rotation_pairs()`: each trim sell ticket matches rotate-in destinations
  IN THE SAME ACCOUNT ONLY (cross-account = a rendered note — contribution/rollover
  territory, never a funded leg). Proceeds allocate by rotate-in rank ×
  underweight gap; max 3 destinations, $2K min leg, whole shares.
- **Style-aware, never forced**: the market layer's own spreads gate the
  growth→dividend boost — equal-weight LEADING +3.0 over cap = "broadening away
  from megacap growth" → SCHD ranks TOP as an income destination for growth-heavy
  sources (SCHG/JEPQ/VUG or >50% growth-sleeve funds). Neutral style or
  non-growth source → no income leg (unit-tested both ways). **The operator's
  "SCHG→SCHD?" question is now literally a card the engine emits the day SCHG
  fires a trim advisory** — today's four live pairs (SPCX/ARKX/XAR/QCOM →
  XLE+XLU, Rollover) show the machinery with both legs ticketed, resulting
  exposures, and the tax note.
- Pair cards SUPERSEDE their singles (folded one-liners in the rail, click to
  expand — never deleted). Buy legs stage PENDING through the family-gated queue.
  `defense_rotation_pairs` table (a `rotation_pairs` table already existed with a
  different schema — namespace checked, renamed). Pair outcomes score as a UNIT
  (source_type=rotation_pair) when the sell slice's round trip closes.
- Field-guard extension: a pair card missing EITHER leg's ticket does not render.

## WS-LAD — ladders you can read
`LadderTrack` — ONE stepper component on trim card faces AND the Rotation Plan:
`[T1 ✓ 35% sold] — [T2 ▲ ARMED · 3 triggers · nearest: close < $30.30] — …`,
14px bold tranche labels on a ~28px track, done=green/armed=amber/fired=red/
disarmed=slate-strike, FIRED segments carry timestamp + cause
(`T2 ⚠ FIRED · Jul 18 · GG escalates to GIVEBACK-BREACH or CLIMAX` — QCOM, live).
Mark-sold action buttons alongside (labels are ACTIONS, not states). Design-guard
census clean.

## Gotchas (new in v6)
- A `rotation_pairs` table already existed (different schema) — CREATE IF NOT
  EXISTS silently no-ops into UndefinedColumn; check namespaces before CREATE.
- Fail-soft rollbacks also roll back UNCOMMITTED DDL — commit CREATE TABLE
  before any code path that might rollback.
- DB triggers (max-2-pending-per-symbol) are AUTHORITATIVE — proposal inserts
  must be fail-soft per row, never allowed to kill the engine run.

## Re-score vs the operator rubric — structural / proven split
**Structural 9.5/10**: every disconnect named in six sessions now has a mechanism —
prescriptions with tickets, pairs that fund them, a core registry the engines obey,
ladders that escalate AND stand down, memory that tracks every slice back in.
**Proven: ~4/10 and accruing on the calendar** — the shadow windows close Jul 30–31
(triple promote), the outcome scoreboards (round trips, tranches, pairs) are
structurally complete but EMPTY until real closes accrue, OI history is at n=1,
and three operator inputs still gate accuracy (options_level, Cost Basis export,
factsheet eyeball). The desk's claims are now falsifiable — which is the point.
