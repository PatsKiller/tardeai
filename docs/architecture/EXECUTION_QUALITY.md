# Replay-Aware Execution Quality (design)

Status:      ACTIVE
as_of:       2026-06-10T21:48:34-04:00
Measured at: efcc51365 / not measured

**Prepared:** 2026-06-10 · **Type:** read-only analytics. No trading writes; validator 12/12.

Separates **outcome** (won/lost) from **execution** (good/poor) using real fill timestamps + intraday bars,
so a *profitable* trade can be flagged *poorly executed* (early entry, no volume confirmation, premature exit,
missed runner). Advisory/evidence-only — never alters live trading decisions.

## Built (foundation phase)
- **Part A — schema** (`migrations/2026-06-10_trade_execution_quality.sql`): `trade_execution_quality`
  (computed metrics, one row per trade, unified Schwab + paper) + `trade_execution_grok_reviews` (LLM
  interpretation stored SEPARATELY). Additive; existing `paper_execution_quality` untouched.
- **Part C — rules** (`config/execution_quality_rules.yaml`): thresholds by strategy family (momentum_scalp,
  gap_and_go, orb, day_trade, swing, dividend, unknown) — RVOL window/min, VWAP requirement, capture/premature
  thresholds, runner multiple, post-exit review window. Loaded, never hardcoded.
- **Part B — compute** (`scripts/build_trade_execution_quality.py`): per trade, reuses the chart bar hierarchy
  (Alpaca→Schwab via `ohlc_charts`) for 1-min bars; computes entry RVOL + volume confirmation, session-VWAP
  relation, RSI/MACD at entry, post-entry MFE/MAE, **capture ratio**, post-exit missed runner (intraday + a
  multi-day daily scan), then deterministic grades: outcome / execution / entry-timing / exit-timing /
  missed-opportunity / discipline, plus flags (no_volume_entry, early_entry, premature_exit, missed_runner)
  and JSONB rule violations. Dry-run default; `--apply` stores. `NO_INTRADAY_PATH`/`NO_VOLUME_DATA` marked
  honestly, never fabricated.

**Proof:** RGNT = WIN/weak (early entry, RVOL 0.64, below VWAP; 10-day post-exit −37% = no runner, exit was
fine). GOVX/FATN = WIN/poor (early entry + premature exit, ~30% capture). NUWE = WIN/poor (12% capture). 48
Schwab trades graded (7 full intraday, 41 NO_INTRADAY_PATH). Validator 12/12.

## Completed (2026-06-10)
- **Part B paper + swings** — paper_trades graded; daily-bars swing path (multi-day holds) added -> 119 OK-path (34 swing + 85 scalp). **Part D** — grok_execution_review.py (7/7 clean JSON). **Part E** — backtest_execution_hypotheses.py + trade_execution_hypothesis_results + /api/v2/backtesting/execution-hypotheses (46 trades x 3 variants; honest negative avg deltas = do-not-blindly-graft). **Part F** — endpoints + journal badges (BOTH Real Accounts + main Trades tab, matched on symbol+entry_time) + replay MFE/MAE overlay + Backtesting-tab hypothesis panel. All 24 trades Grok-reviewed (7 schwab + 17 paper).

## Deferred (named follow-ups)
- **Part B (paper)** — extend `_rows` to paper closed trades (same compute).
- **Part D — Grok normalization** (`scripts/grok_execution_review.py`): feed the COMPUTED metrics to Grok →
  strict JSON (execution_label, mistakes, what-to-do-next, backtest_hypotheses, normalized_tags); store in
  `trade_execution_grok_reviews`; numeric scores stay deterministic.
- **Part E — hypothesis backtests** (`scripts/backtest_execution_hypotheses.py`): test variants (volume-
  confirmed entry, hold-above-VWAP, MACD-rollover exit, trailing after 1R/2R) → `trade_execution_hypothesis_results`;
  evidence-only, never alters live configs.
- **Part F — API/UI**: `/api/v2/journal/execution-quality*` endpoints + journal badges (Outcome/Execution/
  capture/missed) + replay overlays (entry RVOL, session VWAP, post-exit high, MFE/MAE, "you exited here / max here").
