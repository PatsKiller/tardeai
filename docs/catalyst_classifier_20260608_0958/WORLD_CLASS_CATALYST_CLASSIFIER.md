# World-Class Catalyst Classifier (hybrid + outcome-calibrated) — 2026-06-08

Operator-approved: **hybrid engine** (deterministic + local-LLM residual) + **outcome calibration loop**.

## Components
- **`scripts/catalyst_classifier.py`** — `classify(title, summary, symbol) -> {catalyst_type, direction,
  impact_score, confidence, severity, method, rationale, calibration_mult}`.
  1. **Deterministic** (fast, offline): Hermes "<category>:" prefix → typed category; 18-type directional
     regex taxonomy (earnings_beat/miss, guidance up/down, fda, contract, M&A, analyst up/down, insider,
     dividend up/cut, buyback, short_squeeze, ceo_change, offering_dilution, geopolitical…); bull/bear cue
     direction refinement; confidence from match strength.
  2. **Local-LLM residual** (gemma3:4b, free): ONLY when deterministic confidence < 0.55 and not a regex hit;
     structured JSON; timeout + graceful fallback (cold model → deterministic).
  3. **Calibration-aware**: scales impact_score by the per-type learned multiplier (when trusted).
- **`scripts/catalyst_calibration.py`** — daily (`30 5 * * *`), READ-ONLY on prices. Measures realized 2-day
  forward return (ticker_prices) for settled catalysts, scores direction-vs-move, aggregates per type →
  bounded weight_multiplier (0.5–1.5, MIN_SAMPLES=10). Data-quality guards: entry price ≥ $1, |move| ≤ 50%
  dropped as data error. Writes `data/runtime/catalyst_calibration.json`.
- **`scripts/news_to_catalyst.py`** — wired to the classifier (per-run LLM budget = 25 so the 10-min cron
  stays safe); stores direction/confidence/method/rationale/calibration_mult in `raw_payload` (no schema DDL).

## Verified
- Deterministic: fda_approval/bullish 9.5, earnings_miss/bearish 7.2, offering_dilution/bearish 6.2,
  analyst_downgrade/bearish 5.5, Hermes earnings→6.0, news_momentum→4.0 (was flat other/3.0).
- LLM residual (warm): "next-gen platform amid sector buzz" → news_momentum/bullish/0.8.
- Calibration: 4,529 settled, 219 data-errors dropped, 7 trusted types, bounded multipliers (e.g. earnings_miss 1.03, analyst_upgrade 0.74).

## Honest limitations
- Calibration quality is currently limited by (a) old catalysts lacking stored direction (COALESCE→neutral)
  and (b) thin/noisy price coverage on the microcap-heavy catalyst universe (ticker_prices: 41 overlap).
  Multipliers are bounded + data-guarded so this can't zero or explode scoring; it sharpens as
  classifier-labeled catalysts settle and direction labels accumulate.
- Direction stored in raw_payload (no `direction` column) to avoid schema DDL — promote to a column later if desired.

## Safety
Advisory-only; impact feeds fusion catalyst_score; **no GO/WAIT or strategy-scoring change**; non-directional
Hermes-prefix weights avoid injecting false directional bias; LLM budgeted; calibration read-only on prices;
reversible (remove cron line; classifier falls back to base weights if calibration JSON absent).
