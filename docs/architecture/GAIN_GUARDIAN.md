# Gain Guardian — Holdings Exit Intelligence (Live Book, Advisory-Only)

Status:      ACTIVE
as_of:       2026-07-16T12:18:15-04:00
Measured at: efcc51365 / not measured

**Shipped:** 2026-07-16 · **Status:** SHADOW (config `published=false`; operator runs `--promote` after ≥10 trading days)
**Diagnosis:** `docs/_findings/gain_guardian_diagnosis_2026-07-16.md`
**Mode:** Advisory-only. Read-only on every broker surface. Zero LLM calls (deterministic core). No stop moves, no orders, no auto-proposals. Iron-rule holdings check before/after every run.

## What it is
Phase 191's giveback ladder + the protection advisor's technicals, ported to the **real** book, with a parabolic/climax layer and a tax gate on top. Fills the three verified gaps: no parabolic detection, no real-book high-water mark, no tax-aware trim routing.

## Components
| Piece | File / table |
|---|---|
| Metrics engine + HWM (F1) | `scripts/holdings_gain_guardian.py` → `holding_high_water_marks` (ratchet-only, PK symbol+account), `holding_exit_metrics` (row per holding per run) |
| Thresholds + states (F2) | `config/gain_guardian_thresholds.json` (engine reads fresh each run) — parabolic score 0–100, `NORMAL/EXTENDED(≥55)/CLIMAX_RISK(≥75 & rvol≥2)`, `GIVEBACK_WATCH(≥0.25)/BREACH(≥0.40, ≥0.30 at ≥8% weight)` on open gain ≥15% |
| Shadow report (F2) | `scripts/gain_guardian_shadow_report.py` — would-have-fired distribution, near-miss list, SCHG rationale |
| Tax gate (F3) | `scripts/lib/gain_guardian_tax.py` — account routing (prefer IRA/Roth), lot-term honesty, MAGI/IRMAA line via Alex's `get_tax_context()` |
| Publication (F4, dark) | `scripts/lib/gain_guardian_publish.py` — `exit_intelligence` RI rows (mapped to risk_regime in `_TYPE_TO_CAT`), mplfinance chart → `data/runtime/exit_charts/`, ONE Telegram digest/run (dedup `{date}:exit_intel`, 12h window), GAIN GUARDIAN section in `aegis_morning_brief_delivery.py` |
| Outcomes (F5) | `scripts/reconcile_exit_advisory_outcomes.py` → `exit_advisory_outcomes` (+5/+21 trading days vs SPY, drawdown in ATR; verdicts SIGNAL_CORRECT/EARLY/WRONG/NOT_EVALUABLE; fixture self-test) |
| Staging prefill (F6) | `stage_prefill` in every published row's evidence — prefills RI v3 `stage_idea()` (symbol, trim, fraction, exit note so the E3 stop-note gate passes, tax note as funding note, source `gain_guardian`). Operator-clicked only. |

## Cron
- `40 17 * * 1-5` — `holdings_gain_guardian.py --apply` (after the 17:05 protection advisor; 17:35 was taken — diagnosis flag). Post-close, so RVOL uses a full day bar.
- `30 11 * * 0` — `reconcile_exit_advisory_outcomes.py` weekly.

## Adaptations vs original plan (live data won)
1. **`schwab_cost_basis_lots.opened_date` is NULL on 100% of rows** → HWM `lots_history` seeding impossible; seeds from 252-bar close history (`52w_high`) or current price (`provisional` — labeled, capped at REVIEW). Lot LT/ST term is reported as **UNVERIFIED** (assume ST) rather than computed wrong.
2. **Basis hierarchy flipped:** holdings.json per-account basis first (lots are stale 2026-06-10, two accounts only, not account-complete); account-matched lots as fallback; `basis_unknown` suppresses gain-based advisories.
3. **RVOL is fail-soft:** advisor fallback bars carry no volume (funds/proxies) — CLIMAX cannot trigger there and the row says so.
4. **Cron slot:** 17:40 (17:35 occupied by entry_planner/snaptrade/stop_drift).

## First shadow run (2026-07-16, intraday)
32 positions scanned across all four real accounts, 0% provisional HWMs, 0 advisories fired. Top scores: V 46.7 (ext50 3.31 ATR, RSI 74 — nearest to EXTENDED), DXCM 37.7, SCHG 32.6 (RSI 80 but extension/volume sub-threshold; giveback 0.13 < 0.25 watch). Tiny taxable scraps (LDOS/NOC/CACI) show real −25/−40% open losses — giveback gating correctly ignores them (open gain <15%).

## Operator runbook
1. Let the 17:40 shadow runs accumulate ~10 trading days.
2. `python scripts/gain_guardian_shadow_report.py --days 10` — tune `config/gain_guardian_thresholds.json` if the would-have-fired mix looks noisy.
3. `python scripts/holdings_gain_guardian.py --promote` — publication on (RI cards, chart, one digest/run, morning-brief section).
4. Outcomes accrue in `exit_advisory_outcomes`; threshold changes should cite verdict rates.

## Amended-build delta pass (2026-07-16 PM, after morning stop storm)
- **Priority ordering:** candidates evaluate unprotected-large-gain first (no row in stop_lifecycle working/open/awaiting + fidelity_monitored_stops + synthetic_stops, value ≥$10K, rough gain ≥15%), then by position value. NOTE: protection check is SYMBOL-level (any account, any table); per-account share coverage stays the stop supervisor's domain — rows carry "no active stop on file — priority cohort" only when no stop object exists anywhere.
- **RAISE_STOP exclusions:** `is_unstoppable_fund` names (TRIM/REVIEW only) and names whose stop FILLED within ~5 trading days (stop_lifecycle.snapshot_at) never get stop advice; breach advisories keep the trim leg.
- **RVOL renormalization:** missing components renormalize remaining weights (never fabricate volume); `rvol_note: 'n/a (no volume on fallback bars)'` recorded.
- **HWM naming:** `seeded_from='bars_252d'` (existing rows migrated); copy must read "peak over trailing 12m", never "peak since purchase".
- **Tax line (exact):** "holding-period term unverified — export dated Cost Basis from Schwab to confirm LT/ST before acting."
- Charts → `data/runtime/gain_guardian_charts/` (gitignored). Reconciler cron moved to Sunday 09:00.

## OPERATOR ACTION (unlocks v1.1)
Export dated Cost Basis (Realized + Unrealized) CSVs from Schwab for ALL FOUR accounts → `imports/schwab_gainloss/` → rerun `ingest_schwab_gainloss.py --apply`. The current lots table is stale (2026-06-10), missing both rollover IRAs and Fidelity, and 100% date-less — this export unlocks LT/ST verification and purchase-anchored HWMs.
