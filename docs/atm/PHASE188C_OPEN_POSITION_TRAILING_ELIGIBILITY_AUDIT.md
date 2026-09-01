# PHASE 188C — Open-Position Trailing & Profit-Protection Eligibility Audit

Status:      HISTORICAL
as_of:       2026-06-02T08:17:52-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~08:25 ET (premarket) · Alpaca **paper** only · Live endpoint blocked
**Engine:** STOP-V2.3 `scripts/strategy_trailing_policy.recommend_stop()` (recommendation-only;
does not move stops). All quotes STALE (yesterday 16:00 ET) — R values below are computed on the
stale mark and must be re-confirmed at the open.

---

## Per-position audit

| id | Sym | Strategy | Family | Stop set? | Broker stop id | Target? | R (stale) | ≥1R? | Trailing trigger met? | Engine action | After-hrs block |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 28 | NWG | dividend_growth_compounder | income | ✅ 15.05 | ✅ present | ✅ 17.42 | 0.13 | No | No (income 1.5R) | hold | n/a (below tier) |
| 31 | AGNC | reit_income | income | ✅ 9.71 | ✅ present | ✅ 11.24 | 0.03 | No | No | hold | n/a |
| 33 | CMCSA | dividend_growth_compounder | income | ✅ 23.61 | ✅ present | ✅ 27.34 | 0.07 | No | No | hold | n/a |
| 43 | **SNOW** | **unknown_sync** | unknown | ❌ none | ❌ none | ❌ none | n/a* | n/a | **No tiers (unknown family)** | hold — *invalid entry/stop data* | — |
| 47 | TMHC | swing_breakout | swing | ⚠️ 68.02 (value only) | ❌ **none** | ✅ 78.77 | -0.02 | No | No (swing 1.0R) | hold | n/a |
| 48 | **ANY** | **unknown_sync** | unknown | ❌ none | ❌ none | ❌ none | n/a* | n/a | **No tiers (unknown family)** | hold — *invalid entry/stop data* | — |

\* SNOW/ANY: engine returns `invalid entry/stop data` — R cannot be computed because
`planned_stop = None`. The stored `r_multiple` (3.88 / 4.64) is from a separate calc, not the
trailing engine, and is unreliable for stop decisions.

## Findings

### 1. Naked positions (highest priority) — SNOW (43) & ANY (48)
- Both `unknown_sync`, both with **no stop, no target, no broker stop order**.
- Auto-trailing is structurally impossible (unknown family → empty tiers) **and** R is
  uncomputable (no planned_stop). These are **uncovered** — a gap-down at the open is unhedged.
- **ANY is the larger naked exposure:** +$507.58, 619 shares, ~$2.5k notional, no stop.
- Action class: **NEEDS_OPERATOR_REVIEW** (see 188D). Cannot be auto-handled under existing
  policy because policy explicitly has no tiers for `unknown` and forbids auto-action there.

### 2. TMHC (47) — stop value present, broker stop order **missing**
- `planned_stop` is None and `stop_order_id` is None, although the fill note claims
  "Stop: $68.02 (placed after fill)". The DB shows **no working broker stop order**.
- Below trailing threshold (R≈-0.02) so no trailing action — but the **protective stop itself
  should be verified/placed** at the open. Flag for paper-broker order verification.

### 3. Income trades (NWG 28, AGNC 31, CMCSA 33) — correct HOLD
- All properly stopped with live broker stop orders and targets.
- All well below the income first tier (1.5R). Engine correctly returns **hold**. No action.

## Volatility / liquidity context
- ATR not available in `paper_trades` for these rows; ATR present on proposals only.
- Premarket spreads from the feed are stale/garbage (e.g. SNOW bid 267.57/ask none) → **extended-
  hours spread risk is high and unmeasurable right now**. Any stop/target placement must wait for
  the open to avoid setting levels off bad quotes.

## Auto vs. recommend
- **Auto-allowed:** none right now (all `hold` or premarket-stale). No tier fires.
- **Recommend-only / operator:** SNOW & ANY (naked, unknown family), TMHC (verify broker stop).
