# Defense Desk v4 — See the Core · The Round-Trip Ledger · Cards That Show the Trade (2026-07-18)

Status:      ACTIVE
as_of:       2026-07-18T10:51:17-04:00
Measured at: efcc51365 / not measured

Session 4. Operator graded v3 a 4/10: nothing about the core book, no dollars/levels on
cards, 20 rows of honest-empty radar, bottom-list movers celebrated, and no memory of
"step out" advice. v4 fixes each structurally; the remaining points accrue on the
calendar (shadow evidence, OI history, round-trip outcomes).

## WS-L — see the core
- **L1 lookthrough** (`config/fund_lookthrough.json` + `scripts/fund_lookthrough.py`):
  factsheet sector weights for SCHG/SCHD/JEPI/JEPQ/XLI/XLB/XAR/ARKX; SPCX/DIVI/BND
  honestly `lookthrough:none` (~$90K "not decomposed" — never guessed). Engine book
  weights are now EFFECTIVE (direct + lookthrough) with per-sector decomposition.
  **The truth it exposed: Technology 24.1% effective ($257K) vs 5.1% direct — LAGGING;
  Industrials 12.5% effective — LAGGING; both above the 10% hedge trigger v3 never saw.**
  Also fixed: book-map rows carry Finviz sector names — canonicalized via the C2 alias
  map (V's $119K was invisible to Financials; direct Financials was rendering 0%).
- **L2 materiality**: advisory floor max($2K, 0.15% book); 11 residual scraps collapse
  to ONE janitorial CLEANUP card. Move-outs became real: ARKX $30K, XAR $26K, QCOM $9K,
  SPCX $5K — not $600 scraps.
- **L3 stances**: every ≥$10K position (18) renders a stance chip + reason with values —
  INCLUDING HOLD. Funds judged by lookthrough-weighted sector states: SCHG $266K
  TRIM-WATCH (65% of weight in WEAKENING/LAGGING), SCHD $203K HOLD (73% in
  LEADING/IMPROVING), JEPQ TRIM-WATCH (69% weak).

## WS-RT — the round-trip ledger (`scripts/rotation_round_trips.py`)
- Tables `rotation_round_trips` + `round_trip_outcomes`. Lifecycle: advised →
  stepped_out (Schwab `trade_transactions` ingest reconcile — 12h lag known — OR
  one-tap "I executed this" POST `/defense/round-trips/confirm`) → rollback_open
  (conditions stored AT exit from the advisory's own invalidation: sector exits state
  2-close / price reclaims 50DMA / 60 sessions — whichever first) → rolled_back|expired,
  scored vs having held (`source_type=rotation_round_trip`).
- **Wash-sale gate**: taxable exits carry a 31-day countdown + the ANY-account (IRA =
  permanent) disallowance warning; deterministic dates only, "verify with tax context"
  + Alex route; basis unknown until the Cost Basis export lands → chip says so; a wash
  window NEVER suppresses a rollback alert (both facts render).
- Panel on-page with condition chips, distance-to-reentry, confirm buttons. 4 open
  round trips registered day one. Lifecycle unit-tested end-to-end
  (`test_defense_recommendations.py` v4 section, sqlite-backed).

## WS-CARD — cards that show the trade
- Field guard extended: actionable groups REQUIRE `levels` (price/entry/stop) —
  complete-or-absent now includes "actable-from-the-face".
- Per-account dollar bands from live equities ("2–4% ≈ $19.7K–$39.3K (Rollover IRA)");
  the selected account tab drives the band shown.
- CC cards carry a CONCRETE structure from the chain snapshot's `cc_call` pick
  (0.15–0.38Δ, 18–50 DTE, best-fit 0.28Δ): `CSCO · sell 1× 08-21 $125C (~0.27Δ) ·
  est $282 (2.5%) · caps upside at +11.7%`. Chain universe now counts UNIQUE holdings
  (dup V/SCHD rows were silently eating slots — CSCO was missing entirely).
- Impact-descending ordering; top-2 factors on the face; grammar fixed.

## WS-RADAR / WS-BOARD — honest emptiness, honest movement
- Radar collapses to ONE line while every row is baseline (`no unusual hedging across
  27 underlyings · baselines set Jul 18 · history n=1/20d`); the table returns only
  when ≥1 row has signal, and then only signal rows.
- `lib/chipScope.mjs` (plain JS, unit-tested by node IN the npm build): ranks scoped
  to the rendered list, new-to-list dots instead of phantom deltas, and the callout
  separates the strongest IMPROVEMENT (positive movers only) from the sharpest
  DETERIORATION — live: "Energy #2 on M was #8 on Q ▲6" vs "Technology −6.9% on M,
  was top-quartile on Q — the sharpest breakdown".

## Operator mid-session addition — queued refresh
Freshness strip shows each source's last-refresh age; REFRESH ALL POSTs
`/defense/refresh` → detached `defense_refresh_job.py` (flock-single, 4 steps,
per-step status JSON polled by the page). Industries step runs WITHOUT `--close`
(display refresh only — state/debounce stays owned by the 16:18 cron).

## Gotchas (new in v4)
- Book-map sector names are Finviz names — canonicalize before summing sector dollars.
- Chain-universe "top N holdings" must count unique symbols, not holding rows.
- `git checkout` on uncommitted work destroyed a rewrite AGAIN this epoch pattern —
  commit before cleaning scratch edits (second occurrence).

## Self-score vs the operator rubric ("a 10 tells me what to do, in which account, and why")
**Structural 8/10.** What earns it: the core book finally has stances (18/18 covered,
decomposed), every actionable card shows instrument-account-dollars-levels-why on its
face, step-out advice now has a tracked round trip with re-entry conditions and a
wash-sale guard, and the boards/radar say true things or say nothing. What still caps
it — and accrues on the calendar, not in a session: move-out shadow completes ~Jul 31;
OI-delta/P-C history needs ~2 weeks (n=1 today); round-trip outcomes ledger is empty
until the first trips close; options_level still unfilled (put cards locked);
Cost Basis export ×4 pending (wash-sale loss detection runs basis-blind until then).
