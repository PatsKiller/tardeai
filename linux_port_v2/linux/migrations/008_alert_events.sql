-- 008_alert_events.sql — Phase 12: Alert Intelligence Pipeline
-- Run: PGPASSWORD=... psql -h localhost -U trade_ai -d trade_ai -f linux_port_v2/linux/migrations/008_alert_events.sql

BEGIN;

CREATE TABLE IF NOT EXISTS alert_events (
    id                  BIGSERIAL PRIMARY KEY,
    alert_uid           TEXT UNIQUE,
    alert_type          TEXT NOT NULL CHECK (alert_type IN (
        'data_staleness', 'stop_triggered', 'stop_brief', 'portfolio_intelligence',
        'technical_signal', 'draft_pending_review', 'stop_triggered_present',
        'steph_review_needed', 'recovery_watch', 'data_integrity',
        'earnings_alert', 'dividend_alert', 'analyst_alert', 'strategic_alert',
        'system_health', 'cookie_expiry', 'morning_brief', 'aegis_brief',
        'concentration_alert', 'drawdown_alert', 'gain_alert', 'rsi_extreme',
        'volume_spike', 'ma_cross', 'weekly_digest', 'monthly_report'
    )),
    symbol              TEXT,
    severity            TEXT CHECK (severity IN ('info', 'warning', 'urgent', 'critical')),
    source_script       TEXT,
    telegram_message_id TEXT,
    telegram_sent_at    TIMESTAMPTZ,
    raw_text            TEXT,
    parsed_payload      JSONB DEFAULT '{}',
    price               NUMERIC,
    stop_price          NUMERIC,
    gap_pct             NUMERIC,
    position_value      NUMERIC,
    pnl                 NUMERIC,
    decision            TEXT,
    confidence          NUMERIC,
    data_quality_status TEXT DEFAULT 'valid' CHECK (data_quality_status IN (
        'valid', 'unknown', 'stale', 'invalid_zero_price_or_stop',
        'fidelity_scale_anomaly', 'suspicious_freshness_claim',
        'conflicting_values', 'unvalidated'
    )),
    requires_agent_review BOOLEAN DEFAULT FALSE,
    agent_jobs_created  TEXT[],
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_events_symbol ON alert_events (symbol);
CREATE INDEX IF NOT EXISTS idx_alert_events_type ON alert_events (alert_type);
CREATE INDEX IF NOT EXISTS idx_alert_events_severity ON alert_events (severity);
CREATE INDEX IF NOT EXISTS idx_alert_events_created ON alert_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_events_quality ON alert_events (data_quality_status);

-- Links from alerts to other tables (jobs, research cards, etc.)
CREATE TABLE IF NOT EXISTS alert_event_links (
    id                  BIGSERIAL PRIMARY KEY,
    alert_event_id      BIGINT REFERENCES alert_events(id),
    linked_table        TEXT NOT NULL,
    linked_id           TEXT NOT NULL,
    relation_type       TEXT DEFAULT 'triggered',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_links_event ON alert_event_links (alert_event_id);
CREATE INDEX IF NOT EXISTS idx_alert_links_linked ON alert_event_links (linked_table, linked_id);

COMMIT;
