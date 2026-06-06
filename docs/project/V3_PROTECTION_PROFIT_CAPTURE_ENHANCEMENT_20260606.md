# V3 Protection — Canonical Profit-Capture Enhancement (Phase 206, 2026-06-06)

**Status:** Complete. Analytics/advisory/shadow only. No trading behavior changed.

Upgrades the paper-only, open-trade-only protection model to the canonical `trade_instances`
all-trades model, adds evidence-only rule backtesting and shadow threshold recommendations, and
rebuilds the v3 Protection tab with honest, actionable categories.

## Data tables added (additive, idempotent)

`migrations/2026_06_06_phase206_profit_capture.sql`:

- **`trade_profit_capture_analysis`** — one row per closed `trade_instance`, `UNIQUE(trade_instance_id)`.
  Canonical capture metrics + protection failure classification + data-quality flags.
- **`profit_protection_rule_backtests`** — evidence-only candidate-rule results per run.
- **`profit_protection_shadow_recommendations`** — advisory-only threshold recommendations + graft verdict.

### Definitions
```
max_profit_usd       = max favorable open profit during the hold
captured_profit_usd  = realized profit for winners
money_left_usd       = max_profit_usd - captured_profit_usd      (prefers bar money_left)
giveback_pct_of_mfe  = money_left_usd / max_profit_usd
capture_ratio        = captured_profit_usd / max_profit_usd
protection_needed    = winner AND measurable AND max_profit_usd > $50 AND giveback_pct_of_mfe > 0.30
protection_missed    = protection_needed AND (no advisory existed OR advisory came after the peak)
```
`failure_class ∈ { NO_ADVISORY_GENERATED, ADVISORY_TOO_LATE, ADVISORY_IGNORED, STOP_NOT_MOVED,
NO_TAKE_PROFIT, TRAILING_NOT_TRIGGERED, DATA_INCOMPLETE, NOT_PROTECTABLE, UNKNOWN }`.

## Scripts

| Script | Role | Writes |
|--------|------|--------|
| `analyze_profit_capture_all_trades.py` | canonical all-trades analyzer (dry-run default, `--apply`) | `trade_profit_capture_analysis` |
| `diagnose_profit_protection_advisory_gaps.py` | 10-question root-cause per missed winner | none (read-only) |
| `backtest_profit_protection_rules.py` | candidate stop/TP/trailing rules on closed trades | `profit_protection_rule_backtests` |
| `profit_protection_shadow_thresholds.py` | shadow threshold recs + graft verdict | `profit_protection_shadow_recommendations` |
| `profit_protection_advisory.py` | open-trade engine — **additively enriched** (canonical id + audit fields) | `atm_profit_protection_advisories` (unchanged thresholds) |
| `validate_profit_protection_enhancement.py` | end-to-end validation | none |

Never fabricates MFE: trades without bar-based MFE are `measurable=false`, `failure_class=DATA_INCOMPLETE`.

## Canonical analysis results (196 closed trades)

- measurable winners **13** · winners with give-back **9** · money left **$1,239.29**
- protection missed **5** · advisory existed **2** · operator acted **0**
- failure classes: `DATA_INCOMPLETE 117`, `NOT_PROTECTABLE 74`, `NO_ADVISORY_GENERATED 5`
- money left by source: `alpaca_paper $1,239.29` (Schwab give-back unmeasurable — no bars)
- money left by strategy: `momentum_scalp $817.08`, `swing_breakout $217.99`,
  `fib_retracement_bounce $102.55`, `screener $89.70`, `dividend_growth_compounder $11.97`

## Rule backtest (evidence only — never applied to live)

`run_id ppbt_20260606`, 34 measurable trades. **Single-peak approximation** (summary MFE/MAE, not
full intrabar path); `data_quality='approx_single_peak'`, confidence de-rated.

| rule | n | avoided$ | premature$ | net$ | conf | rec |
|------|---|----------|------------|------|------|-----|
| **trail5_after_2R** | 34 | 2,727.77 | 0.00 | **2,727.77** | high | ✅ |
| trail8_after_3R | 34 | 2,214.81 | 0.00 | 2,214.81 | high | ✅ |
| lock50_after_2R | 34 | 1,502.00 | 0.00 | 1,502.00 | high | ✅ |
| lock25_after_1_5R | 34 | 765.83 | 0.00 | 765.83 | high | ✅ |
| partial_tp_1_5R | 34 | 182.02 | 230.12 | −48.10 | medium | ❌ |
| partial_tp_2R | 34 | 101.19 | 142.35 | −41.16 | medium | ❌ |

Best candidate: **trail5_after_2R**. Partial-TP rules show net-negative (premature exit cost > avoided),
correctly **not** recommended.

## Shadow threshold recommendations (advisory only — nothing grafted)

`run_id ppsr_20260606`, MIN_SAMPLE=20. **No family is eligible for graft** — every family is below
the 20-trade evidence floor or its best candidate does not beat baseline:

| family | n | verdict |
|--------|---|---------|
| momentum | 7 | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |
| swing | 18 | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |
| income | 5 | REJECTED_NEGATIVE_EDGE |
| position | 1 | REJECTED_NEGATIVE_EDGE |
| unknown | 3 | DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE |

No config / strategy / GO-WAIT / executor mutation. Operator may approve a strategy-specific pilot.

## Open-trade advisory enrichment (no execution change)

`profit_protection_advisory.py` now adds, per open paper trade: canonical `trade_instance_id`,
`source_system`, `execution_account`, `execution_environment`, plus audit fields
`protectable_profit`, `gain_at_risk`, `giveback_pct_if_stopped`, `current_capture_ratio`,
`threshold_reason`, and `shadow_rule_triggered` (diagnostic-only). Advisory thresholds unchanged;
no stop movement, order submission, or execution added.

## v3 Protection tab

`ProtectionOutcomesPanel.tsx` → `/api/v2/atm/profit-capture` (`scripts/api_v2.py::_atm_profit_capture`):

- **Summary cards:** winners measured, gave back, money left, protection missed, advisory existed,
  operator acted, no advisory generated, rule-backtest potential recovery (shadow).
- **Breakdowns:** by source, failure class, strategy, operator decision, $ left by source/strategy.
- **Trade table:** symbol, source/account, strategy, realized, max$, capture %, money left,
  failure class + advisory status + operator action, data quality, linked `trade_instance_id`.
- **Warnings:** Protection missed / Advisory ignored / Advisory late / Data incomplete.
- **Trust labels:** "Advisory only", "No broker/order changes", "Shadow recommendations do not
  modify GO/WAIT or strategy."

## Remaining gaps (honest)

- Give-back is unmeasurable for the 117 imported Schwab/Fidelity winners (no bar MFE) — flagged
  `DATA_INCOMPLETE`, never fabricated. Closing this needs bar ingestion for imported trades.
- The rule backtest is a single-peak approximation; tick-accurate fills need full bar paths.
- No strategy family yet meets the 20-trade evidence floor, so no threshold change is grafted.

## Safety proof

`ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true`, no `LIVE_TRADING`. Running Hermes drain
untouched (status read only; it neither reads nor writes the backfilled columns). No Phase 205
runtime/timer work. `validate_profit_protection_enhancement.py` → **PASS 10/10**.
