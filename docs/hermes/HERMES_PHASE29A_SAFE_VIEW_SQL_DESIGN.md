# Hermes Phase 29A — Safe View SQL Design

**Date:** 2026-06-01
**Status:** COMPLETE

---

## Views to Create

### 1. hermes_v_journal_learning_context

| Field | Source | Notes |
|-------|--------|-------|
| id | trade_thesis_reviews.id | |
| symbol | trade_thesis_reviews.symbol | |
| strategy_id | trade_thesis_reviews.strategy_id | |
| review_type | trade_thesis_reviews.review_type | |
| trade_status | trade_thesis_reviews.trade_status | |
| thesis_validity | trade_thesis_reviews.thesis_validity | |
| thesis_score | trade_thesis_reviews.thesis_score | |
| execution_score | trade_thesis_reviews.execution_score | |
| risk_management_score | trade_thesis_reviews.risk_management_score | |
| outcome_score | trade_thesis_reviews.outcome_score | |
| lesson_summary | LEFT(lesson_summary, 500) | Truncated |
| created_at | trade_thesis_reviews.created_at | |
| **EXCLUDED** | original_thesis, original_entry_plan, original_risk_plan, original_catalyst, original_agent_views, actual_outcome | Private operational detail |

Source rows: 0 (journal not yet populated — view ready for when data arrives)

### 2. hermes_v_backtest_results_context

| Field | Source | Notes |
|-------|--------|-------|
| id | strategy_backtest_results.id | |
| strategy_id | strategy_backtest_results.strategy_id | |
| symbol | strategy_backtest_results.symbol | |
| setup_type | strategy_backtest_results.setup_type | |
| catalyst_type | strategy_backtest_results.catalyst_type | |
| market_regime | strategy_backtest_results.market_regime | |
| sample_size | strategy_backtest_results.sample_size | |
| wins | strategy_backtest_results.wins | |
| losses | strategy_backtest_results.losses | |
| win_rate | strategy_backtest_results.win_rate | |
| profit_factor | strategy_backtest_results.profit_factor | |
| expectancy_r | strategy_backtest_results.expectancy_r | |
| max_drawdown_r | strategy_backtest_results.max_drawdown_r | |
| confidence_level | strategy_backtest_results.confidence_level | |
| sample_warning | strategy_backtest_results.sample_warning | |
| created_at | strategy_backtest_results.created_at | |
| **EXCLUDED** | None sensitive — all fields are aggregate stats | |

Source rows: 40

### 3. hermes_v_screener_context

| Field | Source | Notes |
|-------|--------|-------|
| id | screener_run_health.id | |
| run_label | screener_run_health.run_label | |
| run_date | screener_run_health.run_date | |
| source | screener_run_health.source | |
| symbols_scanned | screener_run_health.symbols_scanned | |
| go_count | screener_run_health.go_count | |
| wait_count | screener_run_health.wait_count | |
| no_go_count | screener_run_health.no_go_count | |
| status | screener_run_health.status | |
| created_at | screener_run_health.created_at | |
| **EXCLUDED** | input_snapshot, output_snapshot, reason_codes | Large JSONB blobs, internal config |

Source rows: 211

### 4. hermes_v_catalyst_quality_context

| Field | Source | Notes |
|-------|--------|-------|
| id | catalyst_events.id | |
| symbol | catalyst_events.symbol | |
| catalyst_type | catalyst_events.catalyst_type | |
| headline | LEFT(headline, 200) | Truncated |
| severity | catalyst_events.severity | |
| confidence | catalyst_events.confidence | |
| impact_score | catalyst_events.impact_score | |
| source | catalyst_events.source | |
| published_at | catalyst_events.published_at | |
| created_at | catalyst_events.created_at | |
| **EXCLUDED** | raw_payload, source_url, description | raw_payload is large JSONB, source_url may contain tokens |

Source rows: 345

---

## Sensitive Data Check

| View | Account info | Broker credentials | PII | Raw payloads |
|------|-------------|-------------------|-----|-------------|
| journal_learning | NO | NO | NO | Excluded (original_thesis etc.) |
| backtest_results | NO | NO | NO | None present |
| screener | NO | NO | NO | Excluded (snapshots) |
| catalyst_quality | NO | NO | NO | Excluded (raw_payload) |

**All four views are safe for hermes_readonly SELECT access.**
