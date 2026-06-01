# Hermes Phase 28B — Hermes Coverage Gap Audit

**Date:** 2026-06-01
**Status:** COMPLETE — read-only audit

---

## Coverage Assessment

| # | Question | Status | Detail |
|---|----------|--------|--------|
| 1 | Does Hermes read trade journal data? | **NOT COVERED** | No safe view. Journal tables (trade_thesis_reviews, weekly_learning_digests, strategy_lesson_rollup) have no hermes_v_* view. |
| 2 | Does Hermes read journal learning summaries? | **NOT COVERED** | weekly_learning_digest_items, learning_hypotheses, learning_evidence — no Hermes access. |
| 3 | Does Hermes read closed trade case studies? | **PARTIALLY COVERED** | hermes_v_trade_reflection_context shows closed trades (157 rows) but no thesis review or learning summary attached. |
| 4 | Does Hermes read backtesting results? | **NOT COVERED** | strategy_backtest_runs, strategy_backtest_trades, strategy_backtest_results — no safe view. |
| 5 | Does Hermes read rejected/expired proposal replays? | **PARTIALLY COVERED** | hermes_v_proposal_context shows proposals (145 rows) with status field but no backtest replay linkage. |
| 6 | Does Hermes read momentum scout candidates? | **NOT COVERED** | screener_run_health, incubator_universe — no safe view. |
| 7 | Does Hermes read morning briefs? | **NOT COVERED** | File-based only (data/portfolios/reports/). No DB table, no safe view. |
| 8 | Does Hermes read news/catalyst fields? | **CURRENTLY COVERED** | hermes_v_news_research_context (4.9K rows). catalyst_events not yet exposed. |
| 9 | Does Hermes enrich weak catalysts with SearXNG? | **NOT COVERED** | SearXNG exists but no automated catalyst enrichment pipeline. Manual only. |
| 10 | Does Hermes generate backlog items from weak findings? | **PARTIALLY COVERED** | Phase 22 staged 5 backlog items. No automated journal/catalyst→backlog pipeline. |

---

## Coverage Summary

| Status | Count | Surfaces |
|--------|-------|----------|
| CURRENTLY COVERED | 1 | News/catalyst (via safe view) |
| PARTIALLY COVERED | 3 | Closed trades, proposals, backlog generation |
| NOT COVERED | 6 | Journal, learning summaries, backtesting, momentum scout, morning briefs, catalyst enrichment |
| BLOCKED BY SAFE VIEW | 4 | Journal, backtesting, screener, catalyst_events |
| BLOCKED BY STORAGE | 1 | Morning briefs (file-only) |
| BLOCKED BY DESIGN | 1 | SearXNG→catalyst enrichment (needs pipeline approval) |

---

## Gap Priority Matrix

| Gap | Impact | Effort | Priority |
|-----|--------|--------|----------|
| Journal learning visibility | HIGH — core learning loop | LOW — create 1 safe view | P1 |
| Backtesting results visibility | HIGH — strategy validation | LOW — create 1 safe view | P1 |
| Momentum scout visibility | MEDIUM — candidate quality | LOW — create 1 safe view | P2 |
| catalyst_events visibility | MEDIUM — catalyst quality flags | LOW — add to existing grants | P2 |
| Morning brief file scan | MEDIUM — operator intelligence | MEDIUM — file-based scanner | P3 |
| SearXNG catalyst enrichment | HIGH — fills real gap | HIGH — needs pipeline design | P3 |

---

## Recommended Safe View Additions (Future Phase)

| View Name | Source Tables | Fields | Masked/Excluded |
|-----------|-------------|--------|----------------|
| hermes_v_journal_learning_context | trade_thesis_reviews, weekly_learning_digests | symbol, strategy, lesson_type, outcome_category, created_at | Raw thesis text truncated, no account info |
| hermes_v_backtest_results_context | strategy_backtest_runs, strategy_backtest_results | strategy, win_rate, profit_factor, total_trades, sharpe, max_drawdown | No raw config JSON |
| hermes_v_screener_context | screener_run_health, incubator_universe | symbol, screener_name, status, score, catalyst_flags, last_seen | No internal scoring weights |
| hermes_v_catalyst_quality_context | catalyst_events | symbol, event_type, quality_score, freshness, source | No raw payload |
