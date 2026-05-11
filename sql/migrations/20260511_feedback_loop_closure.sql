-- Migration: Feedback Loop Closure
-- Date: 2026-05-11 (Phase 7)
-- Purpose: Track human decisions on CIO recommendations, alert effectiveness,
--          and close the recommendation → outcome → learning loop.

-- ── 1. CIO Decision Response Tracking ───────────────────────────────────

CREATE TABLE IF NOT EXISTS cio_decision_responses (
    id              serial PRIMARY KEY,
    decision_id     text NOT NULL,
    symbol          text NOT NULL,
    action          text NOT NULL,          -- original CIO action (HOLD, ADD, TRIM, etc.)
    response        text NOT NULL,          -- 'accepted', 'rejected', 'deferred', 'ignored'
    response_reason text,
    responded_by    text DEFAULT 'john',
    responded_at    timestamptz DEFAULT now(),
    outcome_tracked boolean DEFAULT false,
    UNIQUE (decision_id)
);

CREATE INDEX IF NOT EXISTS idx_cio_resp_symbol ON cio_decision_responses (symbol);

-- ── 2. Alert Effectiveness Scoring ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS alert_effectiveness (
    id                  serial PRIMARY KEY,
    notification_type   text NOT NULL,
    symbol              text,
    alert_date          date NOT NULL,
    action_taken        boolean DEFAULT false,   -- did user act on this alert?
    action_description  text,
    time_to_action_min  integer,                 -- minutes between alert and action
    effectiveness_score numeric(3,2),            -- 0.0 = ignored, 1.0 = acted immediately
    scored_at           timestamptz DEFAULT now(),
    UNIQUE (notification_type, symbol, alert_date)
);

-- ── 3. Proposal Outcome Chain ───────────────────────────────────────────
-- Links the full chain: proposal → paper_trade → closed P&L → agent feedback

CREATE TABLE IF NOT EXISTS proposal_outcome_chain (
    id                  serial PRIMARY KEY,
    proposal_id         integer NOT NULL,
    symbol              text NOT NULL,
    strategy_id         text,
    proposing_agent     text,
    proposal_created    timestamptz,
    proposal_status     text,                    -- APPROVED, REJECTED, EXPIRED
    paper_trade_id      integer,
    trade_status        text,                    -- open, closed
    trade_pnl           numeric,
    trade_r_multiple    numeric,
    chain_status        text DEFAULT 'pending',  -- pending, linked, closed, orphaned
    outcome_fed_back    boolean DEFAULT false,    -- has this been fed back to agent calibration?
    feedback_at         timestamptz,
    created_at          timestamptz DEFAULT now(),
    updated_at          timestamptz DEFAULT now(),
    UNIQUE (proposal_id)
);

CREATE INDEX IF NOT EXISTS idx_poc_symbol ON proposal_outcome_chain (symbol);
CREATE INDEX IF NOT EXISTS idx_poc_status ON proposal_outcome_chain (chain_status);

-- ── 4. Strategy Performance Snapshots ───────────────────────────────────
-- Weekly auto-generated strategy assessments

CREATE TABLE IF NOT EXISTS strategy_performance_snapshots (
    id              serial PRIMARY KEY,
    snapshot_date   date NOT NULL,
    strategy_id     text NOT NULL,
    period_days     integer DEFAULT 7,
    trades_closed   integer DEFAULT 0,
    wins            integer DEFAULT 0,
    losses          integer DEFAULT 0,
    win_rate        numeric(4,3),
    profit_factor   numeric(6,3),
    avg_r           numeric(4,2),
    total_pnl       numeric,
    assessment      text,                    -- LLM-generated assessment
    recommendation  text,                    -- maintain, review_rules, review_risk_reward
    created_at      timestamptz DEFAULT now(),
    UNIQUE (snapshot_date, strategy_id)
);

-- ── 5. Recovery Outcome Log ─────────────────────────────────────────────
-- When recovery items eventually close, track whether patience was correct

CREATE TABLE IF NOT EXISTS recovery_outcome_log (
    id              serial PRIMARY KEY,
    watch_id        integer REFERENCES stopped_out_watch(id),
    symbol          text NOT NULL,
    exit_type       text NOT NULL,           -- from stopped_out_watch
    final_verdict   text,                    -- what happened: reentered, abandoned, expired
    patience_score  numeric(4,2),            -- patience at resolution
    days_monitored  integer,
    entry_price     numeric,                 -- if reentered, at what price
    reentry_pnl     numeric,                 -- P&L of reentry trade (if any)
    patience_correct boolean,                -- was waiting the right call?
    lesson          text,                    -- what we learned
    resolved_at     timestamptz DEFAULT now(),
    UNIQUE (watch_id)
);

-- ── 6. Agent Calibration Sample Tracking ────────────────────────────────

CREATE TABLE IF NOT EXISTS agent_sample_tracking (
    id              serial PRIMARY KEY,
    agent_name      text NOT NULL,
    snapshot_date   date NOT NULL DEFAULT CURRENT_DATE,
    total_recommendations integer DEFAULT 0,
    resolved        integer DEFAULT 0,
    correct         integer DEFAULT 0,
    wrong           integer DEFAULT 0,
    sample_tier     text,                    -- insight_only, shadow_allowed, promotion_allowed
    accuracy_pct    numeric(5,2),
    days_to_next_tier integer,               -- estimated days to reach next tier
    created_at      timestamptz DEFAULT now(),
    UNIQUE (agent_name, snapshot_date)
);
