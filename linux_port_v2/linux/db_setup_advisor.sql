-- ============================================================
--  OpenClaw Portfolio Advisor — Memory Layer Schema
--  Phase A1: Foundation (dividend_history + advisor_observations)
--  Phase A2: Supervisory (escalation_queue)
--  Run: psql -U trade_ai -d trade_ai -f linux/db_setup_advisor.sql
-- ============================================================

-- ── Dividend History ────────────────────────────────────────────────────────
-- Daily yield/income snapshot per dividend-paying ticker.
-- Enables: yield trend tracking, dividend cut detection, income projection.
CREATE TABLE IF NOT EXISTS dividend_history (
    id serial PRIMARY KEY,
    record_date date NOT NULL,
    symbol varchar(20) NOT NULL,
    annual_yield_pct numeric(6,3),
    quarterly_amount numeric(10,4),
    annual_income numeric(10,2),
    ex_div_date date,
    pay_date date,
    source varchar(30) DEFAULT 'pipeline',
    data jsonb,
    created_at timestamptz DEFAULT now(),
    UNIQUE(record_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_dividend_history_date ON dividend_history(record_date DESC);
CREATE INDEX IF NOT EXISTS idx_dividend_history_symbol ON dividend_history(symbol);

-- ── Advisor Observations ────────────────────────────────────────────────────
-- Append-only agent memory. Each row is one atomic finding.
-- Observations state WHAT IS, never WHAT SHOULD BE.
CREATE TABLE IF NOT EXISTS advisor_observations (
    id serial PRIMARY KEY,
    observed_at timestamptz DEFAULT now(),
    observation_date date NOT NULL,
    symbol varchar(20),
    category varchar(20) NOT NULL,
    observation text NOT NULL,
    evidence jsonb NOT NULL,
    source varchar(50) NOT NULL,
    confidence numeric(3,2) DEFAULT 1.00,
    model varchar(30) DEFAULT 'rule',
    freshness_hash varchar(12),
    UNIQUE(observation_date, symbol, category, source)
);
CREATE INDEX IF NOT EXISTS idx_observations_date ON advisor_observations(observation_date DESC);
CREATE INDEX IF NOT EXISTS idx_observations_symbol ON advisor_observations(symbol);
CREATE INDEX IF NOT EXISTS idx_observations_category ON advisor_observations(category);

-- ── Escalation Queue ────────────────────────────────────────────────────────
-- Observations that crossed an importance threshold and need attention.
-- Escalations are factual threshold-crossings, not recommendations.
CREATE TABLE IF NOT EXISTS escalation_queue (
    id serial PRIMARY KEY,
    created_at timestamptz DEFAULT now(),
    observation_id integer REFERENCES advisor_observations(id),
    symbol varchar(20),
    severity smallint NOT NULL,
    category varchar(20) NOT NULL,
    trigger_rule varchar(50) NOT NULL,
    summary text NOT NULL,
    evidence jsonb NOT NULL,
    status varchar(20) DEFAULT 'pending',
    reviewed_at timestamptz,
    reviewed_by varchar(20),
    expires_at date,
    UNIQUE(observation_id, trigger_rule)
);
CREATE INDEX IF NOT EXISTS idx_escalation_status ON escalation_queue(status, severity);
CREATE INDEX IF NOT EXISTS idx_escalation_created ON escalation_queue(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_escalation_symbol ON escalation_queue(symbol);

-- ── Ticker Snapshot Daily ───────────────────────────────────────────────────
-- Daily enrichment snapshot per ticker. Enables trend detection, analyst shift
-- detection, and historical context for recommendations.
CREATE TABLE IF NOT EXISTS ticker_snapshot_daily (
    id serial PRIMARY KEY,
    snapshot_date date NOT NULL,
    symbol varchar(20) NOT NULL,
    source varchar(20) DEFAULT 'finviz',
    rsi numeric(5,2),
    beta numeric(6,3),
    sma20_pct numeric(6,2),
    sma50_pct numeric(6,2),
    sma200_pct numeric(6,2),
    perf_week_pct numeric(6,2),
    perf_month_pct numeric(6,2),
    perf_ytd_pct numeric(6,2),
    week52_high_pct numeric(6,2),
    week52_low_pct numeric(6,2),
    analyst_recom varchar(20),
    data jsonb,
    created_at timestamptz DEFAULT now(),
    UNIQUE(snapshot_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_ticker_snapshot_date ON ticker_snapshot_daily(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_ticker_snapshot_symbol ON ticker_snapshot_daily(symbol);

-- ── Watchlist Items ─────────────────────────────────────────────────────────
-- Provenance-aware watchlist with support for user, AI-generated, and analyst-curated entries.
CREATE TABLE IF NOT EXISTS watchlist_items (
    id serial PRIMARY KEY,
    symbol varchar(20) NOT NULL,
    source_type varchar(20) NOT NULL,
    thesis text,
    target_intent varchar(30),
    added_date date NOT NULL,
    added_by varchar(30) NOT NULL,
    confidence numeric(3,2),
    status varchar(20) DEFAULT 'active',
    notes text,
    data jsonb,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    UNIQUE(symbol, source_type)
);
CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist_items(status, source_type);
CREATE INDEX IF NOT EXISTS idx_watchlist_symbol ON watchlist_items(symbol);
CREATE INDEX IF NOT EXISTS idx_watchlist_added_date ON watchlist_items(added_date DESC);

-- ── Analyst Consensus History ───────────────────────────────────────────────
-- Daily analyst-related data per ticker. Enables analyst drift detection.
CREATE TABLE IF NOT EXISTS analyst_consensus_history (
    id serial PRIMARY KEY,
    snapshot_date date NOT NULL,
    symbol varchar(20) NOT NULL,
    recom_raw varchar(50),
    recom_score numeric(8,3),
    analyst_rating varchar(30),
    target_price numeric(12,2),
    source varchar(20) DEFAULT 'finviz',
    data jsonb,
    created_at timestamptz DEFAULT now(),
    UNIQUE(snapshot_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_analyst_consensus_date ON analyst_consensus_history(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_analyst_consensus_symbol ON analyst_consensus_history(symbol);

-- ── Yahoo Analyst Targets History ───────────────────────────────────────────
-- Real analyst consensus from Yahoo Finance (mean/high/low/median targets + recommendation scale).
-- Stocks only — ETFs/funds return no data.
CREATE TABLE IF NOT EXISTS yahoo_analyst_targets_history (
    id serial PRIMARY KEY,
    snapshot_date date NOT NULL,
    symbol varchar(20) NOT NULL,
    current_price numeric(12,2),
    target_mean_price numeric(12,2),
    target_high_price numeric(12,2),
    target_low_price numeric(12,2),
    target_median_price numeric(12,2),
    recommendation_mean numeric(8,3),
    recommendation_key varchar(30),
    number_of_analyst_opinions integer,
    source varchar(20) DEFAULT 'yahoo',
    data jsonb,
    created_at timestamptz DEFAULT now(),
    UNIQUE(snapshot_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_yahoo_targets_date ON yahoo_analyst_targets_history(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_yahoo_targets_symbol ON yahoo_analyst_targets_history(symbol);

-- ── Advisor Recommendations ─────────────────────────────────────────────────
-- Conservative review-oriented drafts generated from escalations.
-- Status starts at 'draft'. No auto-execution. No notification without approval.
CREATE TABLE IF NOT EXISTS advisor_recommendations (
    id serial PRIMARY KEY,
    recommendation_date date NOT NULL,
    symbol varchar(20),
    action varchar(30) NOT NULL,
    rationale text NOT NULL,
    confidence numeric(3,2) NOT NULL,
    model varchar(30) NOT NULL,
    escalation_ids integer[],
    observation_ids integer[],
    evidence_summary jsonb NOT NULL,
    status varchar(20) DEFAULT 'draft',
    expires_at date,
    dedupe_key varchar(100) NOT NULL,
    created_at timestamptz DEFAULT now(),
    UNIQUE(dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_advisor_recommendations_status
    ON advisor_recommendations(status, recommendation_date DESC);
CREATE INDEX IF NOT EXISTS idx_advisor_recommendations_symbol
    ON advisor_recommendations(symbol);

-- ── Article Index ───────────────────────────────────────────────────────────
-- Deduped metadata index of all articles/news consumed by the surveillance system.
-- One row per unique article. Dedupe by URL hash.
CREATE TABLE IF NOT EXISTS article_index (
    id serial PRIMARY KEY,
    ingested_at timestamptz DEFAULT now(),
    published_at timestamptz,
    title text NOT NULL,
    url text,
    source varchar(50) NOT NULL,
    provider varchar(30),
    symbols varchar(20)[],
    portfolio_symbol varchar(20),
    relevance_score integer,
    sentiment varchar(10),
    impact_tier varchar(20),
    llm_category varchar(30),
    llm_urgency varchar(10),
    summary text,
    data jsonb,
    dedupe_key varchar(100) NOT NULL,
    UNIQUE(dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_article_published ON article_index(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_article_symbols ON article_index USING gin(symbols);
CREATE INDEX IF NOT EXISTS idx_article_portfolio_symbol ON article_index(portfolio_symbol);
CREATE INDEX IF NOT EXISTS idx_article_ingested ON article_index(ingested_at DESC);

-- ── Notification Log ────────────────────────────────────────────────────────
-- Audit trail for all notifications sent or attempted.
CREATE TABLE IF NOT EXISTS notification_log (
    id serial PRIMARY KEY,
    created_at timestamptz DEFAULT now(),
    notification_date date NOT NULL,
    notification_type varchar(30) NOT NULL,
    channel varchar(20) NOT NULL,
    subject text,
    body_summary text,
    recommendation_ids integer[],
    escalation_ids integer[],
    observation_ids integer[],
    payload jsonb,
    status varchar(20) DEFAULT 'queued',
    dedupe_key varchar(100) NOT NULL,
    sent_at timestamptz,
    error text,
    UNIQUE(dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_notification_date ON notification_log(notification_date DESC);
CREATE INDEX IF NOT EXISTS idx_notification_status ON notification_log(status);
CREATE INDEX IF NOT EXISTS idx_notification_type ON notification_log(notification_type);
