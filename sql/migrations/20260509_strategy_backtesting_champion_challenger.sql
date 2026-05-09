-- Strategy Backtesting + Champion/Challenger: Session 31
-- 2026-05-09 Idempotent

CREATE TABLE IF NOT EXISTS backtest_datasets (
    id BIGSERIAL PRIMARY KEY, dataset_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
    source_type TEXT NOT NULL, symbols JSONB DEFAULT '[]'::jsonb,
    start_date DATE, end_date DATE, bar_interval TEXT, rows_count INTEGER DEFAULT 0,
    missing_data_notes TEXT, assumptions JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS strategy_backtest_runs (
    id BIGSERIAL PRIMARY KEY, run_id TEXT UNIQUE NOT NULL, strategy_id TEXT,
    strategy_name TEXT, run_type TEXT NOT NULL, status TEXT DEFAULT 'created',
    dataset_id TEXT, config_source TEXT, config_key TEXT, config_snapshot JSONB,
    start_date DATE, end_date DATE, symbols JSONB DEFAULT '[]'::jsonb,
    assumptions JSONB DEFAULT '{}'::jsonb, cost_model JSONB DEFAULT '{}'::jsonb,
    slippage_model JSONB DEFAULT '{}'::jsonb, started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ, duration_seconds NUMERIC, error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sbr_strategy ON strategy_backtest_runs(strategy_id);
CREATE INDEX IF NOT EXISTS idx_sbr_status ON strategy_backtest_runs(status);

CREATE TABLE IF NOT EXISTS strategy_backtest_trades (
    id BIGSERIAL PRIMARY KEY, simulated_trade_id TEXT UNIQUE NOT NULL,
    run_id TEXT NOT NULL, strategy_id TEXT, symbol TEXT NOT NULL,
    signal_time TIMESTAMPTZ, entry_time TIMESTAMPTZ, exit_time TIMESTAMPTZ,
    direction TEXT DEFAULT 'long', entry_price NUMERIC, stop_price NUMERIC,
    target_price NUMERIC, exit_price NUMERIC, shares NUMERIC, risk_amount NUMERIC,
    pnl NUMERIC, pnl_pct NUMERIC, r_multiple NUMERIC,
    max_favorable_excursion NUMERIC, max_adverse_excursion NUMERIC,
    exit_reason TEXT, signal_payload JSONB DEFAULT '{}'::jsonb,
    execution_assumptions JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sbt_run ON strategy_backtest_trades(run_id);
CREATE INDEX IF NOT EXISTS idx_sbt_symbol ON strategy_backtest_trades(symbol);

CREATE TABLE IF NOT EXISTS strategy_backtest_results (
    id BIGSERIAL PRIMARY KEY, result_id TEXT UNIQUE NOT NULL, run_id TEXT NOT NULL,
    strategy_id TEXT, total_signals INTEGER DEFAULT 0, simulated_trades INTEGER DEFAULT 0,
    closed_trades INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0,
    win_rate NUMERIC, gross_profit NUMERIC, gross_loss NUMERIC, profit_factor NUMERIC,
    expectancy_r NUMERIC, avg_r NUMERIC, median_r NUMERIC, max_drawdown NUMERIC,
    avg_hold_minutes NUMERIC, stop_hit_rate NUMERIC, target_hit_rate NUMERIC,
    avg_slippage_bps NUMERIC, avg_spread_bps NUMERIC, sharpe_like NUMERIC,
    sample_size_status TEXT, limitations JSONB DEFAULT '[]'::jsonb,
    metrics JSONB DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sbrr_run ON strategy_backtest_results(run_id);

CREATE TABLE IF NOT EXISTS challenger_definitions (
    id BIGSERIAL PRIMARY KEY, challenger_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
    domain TEXT NOT NULL, strategy_id TEXT, champion_key TEXT,
    challenger_type TEXT NOT NULL, champion_config JSONB, challenger_config JSONB NOT NULL,
    diff JSONB, created_from_recommendation_id TEXT, created_from_hypothesis_id TEXT,
    status TEXT DEFAULT 'draft', created_by TEXT DEFAULT 'system',
    created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cd_strategy ON challenger_definitions(strategy_id);
CREATE INDEX IF NOT EXISTS idx_cd_status ON challenger_definitions(status);

CREATE TABLE IF NOT EXISTS champion_challenger_results (
    id BIGSERIAL PRIMARY KEY, comparison_id TEXT UNIQUE NOT NULL,
    challenger_id TEXT NOT NULL, champion_run_id TEXT, challenger_run_id TEXT,
    strategy_id TEXT, dataset_id TEXT, comparison_status TEXT DEFAULT 'completed',
    champion_metrics JSONB, challenger_metrics JSONB, delta_metrics JSONB,
    verdict TEXT, sample_size INTEGER DEFAULT 0, confidence NUMERIC,
    risk_notes TEXT, recommendation TEXT, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS backtest_learning_evidence_links (
    id BIGSERIAL PRIMARY KEY, link_id TEXT UNIQUE NOT NULL, run_id TEXT,
    result_id TEXT, challenger_id TEXT, comparison_id TEXT, evidence_id TEXT,
    hypothesis_id TEXT, recommendation_id TEXT, proposal_id TEXT,
    link_type TEXT, link_confidence NUMERIC DEFAULT 1.0,
    payload JSONB DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS backtest_run_log (
    id BIGSERIAL PRIMARY KEY, log_id TEXT UNIQUE NOT NULL, run_id TEXT,
    script_name TEXT, mode TEXT, started_at TIMESTAMPTZ DEFAULT now(),
    finished_at TIMESTAMPTZ, status TEXT DEFAULT 'running',
    records_read INTEGER DEFAULT 0, trades_simulated INTEGER DEFAULT 0,
    results_written INTEGER DEFAULT 0, errors JSONB DEFAULT '[]'::jsonb,
    summary JSONB DEFAULT '{}'::jsonb
);
