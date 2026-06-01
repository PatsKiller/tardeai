-- Hermes Phase 29 — Safe views for journal, backtesting, screener, catalyst
-- Date: 2026-06-01
-- Purpose: Read-only Hermes access to Trade AI learning surfaces
-- No source table mutations. SELECT-only grants.

BEGIN;

-- 1. Journal Learning Context
CREATE OR REPLACE VIEW hermes_v_journal_learning_context AS
SELECT
    id,
    symbol,
    strategy_id,
    review_type,
    trade_status,
    thesis_validity,
    thesis_score,
    execution_score,
    risk_management_score,
    outcome_score,
    LEFT(lesson_summary, 500) AS lesson_summary,
    created_at
FROM trade_thesis_reviews;

COMMENT ON VIEW hermes_v_journal_learning_context IS 'Hermes safe view — trade thesis review scores and lessons (no raw thesis/plans/outcomes)';

-- 2. Backtest Results Context
CREATE OR REPLACE VIEW hermes_v_backtest_results_context AS
SELECT
    id,
    strategy_id,
    symbol,
    setup_type,
    catalyst_type,
    market_regime,
    sample_size,
    wins,
    losses,
    win_rate,
    profit_factor,
    expectancy_r,
    max_drawdown_r,
    confidence_level,
    sample_warning,
    created_at
FROM strategy_backtest_results;

COMMENT ON VIEW hermes_v_backtest_results_context IS 'Hermes safe view — backtest aggregate stats (no config snapshots)';

-- 3. Screener Context
CREATE OR REPLACE VIEW hermes_v_screener_context AS
SELECT
    id,
    run_label,
    run_date,
    source,
    symbols_scanned,
    go_count,
    wait_count,
    no_go_count,
    status,
    created_at
FROM screener_run_health;

COMMENT ON VIEW hermes_v_screener_context IS 'Hermes safe view — screener run health (no input/output snapshots)';

-- 4. Catalyst Quality Context
CREATE OR REPLACE VIEW hermes_v_catalyst_quality_context AS
SELECT
    id,
    symbol,
    catalyst_type,
    LEFT(headline, 200) AS headline,
    severity,
    confidence,
    impact_score,
    source,
    published_at,
    created_at
FROM catalyst_events;

COMMENT ON VIEW hermes_v_catalyst_quality_context IS 'Hermes safe view — catalyst events (no raw_payload/source_url)';

-- Grants — SELECT only to hermes_readonly
GRANT SELECT ON hermes_v_journal_learning_context TO hermes_readonly;
GRANT SELECT ON hermes_v_backtest_results_context TO hermes_readonly;
GRANT SELECT ON hermes_v_screener_context TO hermes_readonly;
GRANT SELECT ON hermes_v_catalyst_quality_context TO hermes_readonly;

COMMIT;
