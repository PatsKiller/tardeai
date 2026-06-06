# Profit-Capture Rule Backtest — Hardening (Phase 206b, 2026-06-06)

**Status:** Complete. Evidence-only analytics. No trading behavior changed. Validation **PASS 13/13**.

Implements the remediation from `PROFIT_CAPTURE_BACKTEST_QUALITY_REVIEW_20260606.md`: the rule
backtest no longer overstates evidence quality, separates winner give-back from loser risk-control,
reports reliable sample size, and labels premature-exit uncertainty honestly. Every shadow
recommendation stays blocked.

## What changed

### Schema (additive, idempotent) — `migrations/2026_06_06_phase206b_backtest_quality.sql`
Added nullable columns to `profit_protection_rule_backtests`: `raw_sample_size`,
`quality_eligible_sample_size`, `triggered_sample_size`, `winner_sample_size`,
`reliable_sample_size`, `excluded_count`, `excluded_reasons`, `premature_exit_cost_known`,
`premature_exit_cost_method`, `premature_exit_cost_warning`, `estimate_quality`, `result_scope`,
`graft_verdict`.

### `scripts/backtest_profit_protection_rules.py`
- **Data-quality gate** (`--quality-gated`, `--min-bars-analyzed`, `--max-mfe-r`,
  `--require-planned-stop`): drops trades with too-few MFE bars, outlier `mfe_r`, no planned stop,
  or `max_profit ≤ 0`. Row-level flags: `has_bar_path`, `bars_analyzed`, `has_planned_stop`,
  `has_valid_mfe`, `mfe_outlier`, `is_winner`, `eligible_for_giveback_rule`,
  `eligible_for_breakeven_rule`, `reliable`, `excluded_reason`.
- **Winners-only give-back scope** (`--winners-only`, `--separate-losers`): give-back rules score
  winners only; breakeven/loss-prevention is reported separately as `risk_control`.
- **Multi-tier sample reporting:** raw / quality-eligible / triggered / winner / reliable.
- **Confidence keyed to reliable n** (`insufficient <10 / weak <20 / moderate <50 / stronger ≥50`).
- **Honest premature-exit cost:** under single-peak MFE, `premature_exit_cost_known=false`,
  `premature_exit_cost_warning=single_peak_mfe_cannot_order_stop_trigger_vs_later_profit`,
  `estimate_quality=upper_bound_single_peak`. Recovery is an upper bound.
- **Graft gate:** `reliable_n < 20 → DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE`; `net ≤ 0 → REJECTED_NEGATIVE_EDGE`;
  `premature unknown → DO_NOT_GRAFT_PREMATURE_COST_UNKNOWN`.

### `scripts/profit_protection_shadow_thresholds.py`
- Verdict now keys off **`reliable_sample_size`** (not raw family n) and `premature_exit_cost_known`.
- Hard rules: `reliable_n < 20 → DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE`; premature-cost-unknown cannot
  be `ELIGIBLE_FOR_OPERATOR_REVIEW` without explicit `--operator-override`.
- Latest backtest run selected by recency (`created_at`), not string order.

### `/api/v2/atm/profit-capture` + v3 `ProtectionOutcomesPanel.tsx`
- Endpoint surfaces `rule_backtest_reliable_n`, `rule_backtest_raw_n`,
  `rule_backtest_estimate_quality`, `rule_backtest_premature_cost_known/warning`,
  `rule_backtest_graft_verdict`, plus `labels.estimate` / `labels.graft`.
- UI: "Rule recovery (~UB)" card shows reliable n; a qualifier banner shows best rule, reliable n
  (vs raw), estimate quality, graft verdict, and the upper-bound/premature warning. Directional
  signal retained but qualified.

## Before / after rule evidence

| | Before (raw, ungated) | After (quality-gated, winners-only) |
|---|---|---|
| best rule (by net) | `trail5_after_2R` | `scalp_fast_trail3_after_1_5R` (then `trail5_after_2R`) |
| reported sample | `n=34` | raw 34 → **reliable 2** (`trail5`), reliable 1 (`scalp`) |
| recovery | `$2,727.77` (point estimate) | `$447` **upper bound** (single-peak), reliable n=2 |
| premature-exit cost | `$0.00` (precise) | **unknown** (flagged; cannot be priced under single-peak) |
| confidence | `high` | **insufficient** (keyed to reliable n) |
| graft verdict | (implied recommend) | **DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE** (all rules) |

Exclusions (give-back scope, all-population rules): of 34 measurable, ~32 excluded — dominant
reasons `bars_lt_10`, `not_winner`, `no_planned_stop`, `mfe_r_gt_20`. Reliable winner sample = 2.

## Shadow recommendations (advisory only — nothing grafted)

run `ppsr_qg_20260606`: every family `DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE`, confidence `insufficient`,
reliable n ∈ {0,1,2}. No config / strategy / GO-WAIT / executor mutation.

## Premature-exit limitation (explicit)

We have summary MFE/MAE, not the full intrabar path. A trail/lock floor is modelled as binding only
after the favorable peak (single-peak). This **cannot** detect an earlier stop-out, so it
under-states premature-exit cost and the recovery figure is an **upper bound**, not a fill-accurate
result. Pricing premature-exit cost requires intrabar bars; until then, `premature_exit_cost_known=false`.

## Safety proof

`ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true`, no `LIVE_TRADING`. No broker/order/stop/
proposal/GO-WAIT/strategy/YAML mutation; no live enablement; no Phase 205 work; Hermes drain
untouched. `validate_profit_capture_rule_quality.py` → **PASS 13/13**.
