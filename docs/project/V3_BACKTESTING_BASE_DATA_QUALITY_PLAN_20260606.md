# v3 Backtesting Base Data Quality Scorecard (2026-06-06)

Status:      ACTIVE
as_of:       2026-06-06T11:36:30-04:00
Measured at: efcc51365 / not measured

ADVISORY ONLY — does not affect GO/WAIT or any trading behaviour. Surfaces how trustworthy each
Backtesting tab's underlying data is. `scripts/validate_backtesting_base_data_quality.py` (read-only).

## Trust tiers (trade_llm_reviews, 2026-06-06)
- Excellent (exact trade_instance + account, exact_* confidence): 28
- Usable (exact source/backtest row, no trade_instance): 2052
- Advisory-only (simulation or unlinked): 2075
- Untrusted (stale-basis or infra/parser error): 1788

## Per-tab data trust (current)
- AI Trade Eval: 51 rows · 24 trade_instance-linked · account 47% · provenance 100%.
- Entry Quality: 95 rows · 92 trade_instance-linked (96.8%).
- Edge Comparison: 101 rows · trade_instance-linked (paper 43 proposal-edge + schwab 58 per-trade-backtest).
- Hermes Reflections: 1482 rows · 42 trade_instance-linked · closed backlog 148 (manual drain).
- LLM Review Coverage: 2105 rows · provenance 100% · infra-errors 1671 (retryable) · parser 60 · stale 10.
- Missed Opportunities: deduped by proposal_id; verdict incl MIXED.

## Categories (proposed dashboard labels)
- Excellent: exact trade_instance_id + account + strategy + source + clean data_quality.
- Usable: exact source/backtest row but no trade_instance.
- Advisory only: simulation-only or MIXED outcome.
- Untrusted: stale basis / infra-error / parser-error / no provenance.

## Recommendation
Surface the scorecard as a small read-only "data trust" strip on the Backtesting page (per-tab badge:
Excellent/Usable/Advisory/Untrusted). Keep advisory; never gate GO/WAIT. Improve upstream import lineage
(strategy_id on imported trades) + drain Hermes backlog (operator-approved) to raise scores over time.

## Safety
Read-only diagnostic. No trading/GO-WAIT/strategy/Phase-205 impact.

## Surfaced in UI (2026-06-06)
- Endpoint `/api/v2/backtesting/data-quality` returns per-tab {tier, pct, linked, basis} + legend.
- v3 Backtesting tabs now show a colored **data-trust dot** (Excellent green / Usable blue / Advisory amber
  / Untrusted red) on Entry Quality, AI Trade Eval, Missed, LLM Review Coverage, with a hover tooltip
  (tier + % linked/clean + basis) and a legend strip ("advisory only — does not affect GO/WAIT").
- Current tiers: entry_quality EXCELLENT (97%) · edge_comparison EXCELLENT (100%) · trade_eval ADVISORY
  (47%) · missed ADVISORY · hermes_reflections UNTRUSTED (22%, backlog) · llm_review_coverage UNTRUSTED
  (15% clean — infra errors retryable, separate). Honest; advisory only.
