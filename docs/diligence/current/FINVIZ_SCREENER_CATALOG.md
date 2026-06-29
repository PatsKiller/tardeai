# Finviz Screener Catalog

_Canonical catalog of every Finviz screener. Source of truth: `config/finviz_screeners.yaml`
(validated against the live `finviz_screeners` DB by `validate_finviz_screener_registry.py`)._

**Finviz screens are DISCOVERY ONLY.** No screener is GO-eligible by itself (`go_eligible_by_itself:
false`). A momentum_scalp GO still requires the strict downstream deterministic gates: float ≤ 20M,
RVOL ≥ 5, price in bounds, **verified catalyst, fresh quote, route=momentum_scalp, actionability=GO,
not a Social Scout, not a large-float scout, valid plan, and all validation/risk/liquidity/TTL gates**.

## Operator-provided purpose-built presets (5)

| Name | Preset | Strategy family | Cadence class | Use | Active |
|------|--------|-----------------|---------------|-----|:------:|
| Momentum Scalp — Primary Premarket High-RVOL Gappers | `s144880153` | momentum_scalp | **scalp_fast** | premarket scalp/gapper discovery (float<50M, RVOL>5, gap>10%, $2–20) | ✅ |
| Momentum Scalp — Lower-Price Active Gappers | `s144880160` | momentum_scalp | **scalp_fast** | broader active low-price gappers ($1–10, RVOL>2, gap>5%) | ✅ |
| Momentum Scalp — Intraday Continuation / Change-From-Open | `s144880157` | momentum_scalp | **scalp_fast** | post-open continuation (09:30–11:30 ET, chg-from-open 5–50%) | ✅ |
| Swing — Small-Cap Quality Trend Extension | `s144880159` | swing | **swing_daily** | small-cap quality/trend-extension (NOT scalp) — 1–2×/day | ✅ |
| Swing — Small-Cap Uptrend Pullback | `s144880158` | swing | **swing_intraday** | uptrend pullback (NOT scalp) — 2–3×/day | ✅ |

Full URLs + filters are in `config/finviz_screeners.yaml`.

### Broad-discovery vs strict-GO split

The scalp presets use **float < 50M** (broad discovery) — deliberately wider than the momentum_scalp GO
gate (**float ≤ 20M**). The screens surface candidates; the deterministic gates decide tradeability. A
candidate from these screens can become a **Social Scout** (2–4 pillars, never tradeable) or, only if it
independently passes every GO gate, a `momentum_scalp` GO. Finviz alone never creates GO.

## The 5-minute scalp lane runs ONLY these (`scalp_lane_screener_ids`)

`momentum_scalp_primary_gappers`, `momentum_scalp_low_price_active_gappers`, and
`momentum_scalp_intraday_continuation` (the last only inside 09:30–11:30 ET). It **does not** run
`finviz_screener_runner.py --run` (which would fire all 29 DB screeners) — enforced by
`tests/test_momentum_scalp_finviz_lane_not_broad.py`.

## DB screeners (29) — by strategy family + cadence class

The live `finviz_screeners` table holds **29 screeners, all income / swing / fundamental — NONE are
momentum_scalp** (the scalp screen was operator-excluded from the DB). They are catalogued in
`config/finviz_screeners.yaml` under `db_screeners` (`classification_status: needs_review` until
operator-confirmed). They must run on their own cadence class, **never at 5-min scalp cadence**:

| Cadence class | Families / examples | Recommended run |
|---------------|---------------------|-----------------|
| **scout_intraday** | speculative_growth (speculative_catalyst, tactical_momentum), recovery_watch | every 15 min, 06:00–12:00 |
| **swing_intraday** | swing_trade (swing_momentum, oversold_reversion), fib_retracement_bounce | 09:45 / 12:30 / 15:30 |
| **swing_daily** | swing_breakout, sector_rotation, defense_thesis | 10:00 / 15:30 |
| **fundamental_daily** | core_index, core_growth_compounder, dividend_growth_compounder | 17:00 |
| **income_weekly** | bond_income, covered_call_income, high_yield_income_bdc, reit_income, international_dividend, income_add | Sat 09:00 |

See `FINVIZ_SCREENER_EFFICIENCY_AUDIT.md` for per-screener overlap/yield + keep/reduce/merge/sunset
recommendations, and `config/finviz_screener_cadence_policy.yaml` for the cadence class definitions.

## Governance

* **Admin panel "Finviz Screener Governance"** — command-center-v3 **System → Finviz** tab
  (`FinvizScreenerPanel`). View/manage every registry screener: strategy family, cadence class,
  active flag, notes, **next/last run + row count**, scalp-lane membership, and **run-now (SOURCE
  FETCH ONLY — never a trade, never a gate bypass)**. Edits are audit-logged via `admin_write_guard`
  (operator, timestamp, before→after).
* **API** (`finviz_admin_api.py`, delegated from `api_v2.handle()`):
  * `GET  /api/admin/finviz-screeners` — list (registry+DB merge, cadence, next/last run)
  * `GET  /api/admin/finviz-screeners/audit` — efficiency audit
  * `POST /api/admin/finviz-screeners/:id/update` — cadence_class / notes / sunset_candidate (metadata only)
  * `POST /api/admin/finviz-screeners/:id/enable | /disable` — DB `active` flag
  * `POST /api/admin/finviz-screeners/:id/run-now` — throttle-safe Finviz fetch via
    `run_finviz_targeted_screeners` (no broker path, no order submission)
* `validate_finviz_screener_registry.py` fails the build if the DB and registry drift.

No live broker writes. Operator confirmation / 2FA untouched. LLMs advisory only. No screener is
GO-eligible by itself — strict momentum_scalp gates (float ≤20M, RVOL ≥5, verified catalyst, fresh
quote, route, valid plan) apply downstream regardless of which screen surfaced the symbol.
