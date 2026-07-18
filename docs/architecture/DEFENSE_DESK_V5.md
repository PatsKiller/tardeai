# Defense Desk v5 — Dynamic Trims · Sell Tickets · Exit Ladders · The Rotation Plan (2026-07-18)

Session 5. One capability in three parts, no cut line: WS-DT → WS-EL → WS-RP all shipped.
The static "trim 25–50%" band is dead — and the field guard makes its return impossible.

## WS-DT — dynamic trims + sell tickets (`scripts/defense_trim_ladders.py`)
- **compute_trim_plan()** — deterministic composite, ARITHMETIC ON THE CARD:
  factor-severity base (2→20 / 3→30 / 4+→40, urgent 40) · GG modifier (giveback-watch
  +5, breach +15, EXTENDED/CLIMAX floor 25 — fraction not persisted by GG, floor from
  state with the absence NOTED) · concentration overage above the 12% target (cap +15)
  · stop context (unprotected +5 / tight stop −5; an engaged GG state counts as
  protection). Bounds 15–60, round to 5. Absent inputs listed, never silently defaulted.
  **Live day one, four different fractions:** ARKX 35 (3 factors + giveback-watch),
  XAR 35 (3 factors + unprotected), SPCX 45 (4 factors + unprotected), QCOM 60
  (4 factors + giveback-breach +15 + concentration +12, bounded).
- **sell_ticket()** — per-account estimates: whole shares (floor), as-of-labeled price,
  proceeds, position-after, and resulting effective-sector exposure from the lookthrough
  ("QCOM 60% → Technology effective 24.1% → 23.5%"). Multi-account symbols: IRA-first
  ordering; the taxable slice renders as a LABELED harvest option with the wash chip —
  both shown, never auto-chosen. Fund positions judge concentration via their dominant
  lookthrough sleeve.
- **Field guard extension**: `moveout-*` cards REQUIRE `trim_rationale` + `ticket` —
  a ticket-less trim card does not render (unit-tested).

## WS-EL — exit ladders (`rotation_ladders` table)
- Every trim advisory arms **T2** (+25pp; **T3** when urgent) at creation with triggers
  FROZEN then, machine-evaluable only: sector persistence (N more sessions), price level
  (**hosted on the existing 20-min `watch_alerts` evaluator** — `price_cross_below`
  rows, created_by=defense_ladder; 4 registered day one), GG escalation, factor-count
  increase.
- Nightly evaluation runs BOTH paths: trigger confirms → tranche **FIRES** (card
  escalates; Telegram post-promote) · sector recovers → tranche **DISARMS** with the
  reason rendered — ladders stand down visibly, never linger. **QCOM's T2 fired on day
  one from a real GIVEBACK-BREACH.** Fire and disarm both unit-tested.
- Tranche-granular execution: `POST /defense/round-trips/confirm {ladder_id, tranche}`;
  stance strip shows inline progress ("T1 45% advised · T2 armed").

## WS-RP — the Rotation Plan
- **RP1**: a confirmed tranche opens a re-entry watch for THE SLICE —
  `rotation_round_trips.tranche_of` keys it to the ladder (Phase-0 decision: reuse the
  RT machinery; conditions/wash/outcome logic applies verbatim). Unit-tested lifecycle.
- **RP2**: the **Rotation Plan panel** sits above the rail — one row per position with
  any active rotation state: stance · T1 state + tranche chips (armed w/ trigger
  tooltips, FIRED w/ cause, DISARMED w/ reason) · re-entry condition chips with
  met-state · wash line · now-vs-exit distance · mark-sold buttons. Honest empty state.
- **RP3**: morning brief gains a `*Rotation:*` one-liner (fail-open, dry-run verified);
  the Home posture strip shows the count chip (plans/armed/FIRED/rollback-open) via the
  posture payload; rollback/tranche events join the post-promote Telegram digest.

## Gotchas (new in v5)
- GG persists advisory/severity/extension/giveback STATES but NOT
  `suggested_trim_fraction` — the composite floors from state and says so.
- Confirm-button labels must read as ACTIONS ("mark T1 sold") — "T1 executed" renders
  as a status and lies.
- holdings.json uses `shares` (the prompt's `quantity` probe returned None).
- Append-then-move test-runner blocks: three sessions running, the appended function
  landed after `__main__` twice more — write the runner last, always.

## Re-score vs the operator rubric ("a 10 tells me what to do, in which account, and why")
**Structural 9/10.** The desk now says: what to sell, how many shares, in which account
(with the tax fork shown), at what estimated proceeds, what the position and sector
exposure become, when to sell MORE (armed triggers with live distances), when to STOP
selling (visible disarms), and when to come back in (re-entry watches per slice).
**Calendar, not code, holds the last point:** the Jul 30–31 combined shadow review
(GG + move-out promote — now also deciding whether ladders/rollback alerts earn
Telegram); round-trip and tranche outcomes accruing into the scoreboard; OI history
(n=1→20d); operator items — options_level, Cost Basis export ×4 (term math + wash
loss detection + ticket realized-gain estimates), factsheet eyeball, KEY ROTATION.
