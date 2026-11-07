-- LQ-20261107-332 / SPEC_MARKET_EVENT_REENTRY_20261107 §4.1–4.2: market-event episodes and re-entry candidates.
--
-- Written by lane market-event-detect (scripts/market_event_detect.py --apply). Advisory only: nothing here sizes,
-- orders or reaches a broker. WP3 (market_event_plan) reads these tables read-only. Additive only; applied by the
-- lead, not by the worker. Column names follow spec §4 verbatim, plus `scope` (one open episode per kind+scope)
-- and `last_eval` (the detector's last evaluation, so closure counts survive between runs).

CREATE TABLE IF NOT EXISTS market_event_episodes (
    episode_id       TEXT        PRIMARY KEY,                 -- <kind>:<scope>:<baseline_date>
    kind             TEXT        NOT NULL CHECK (kind IN ('broad_selloff', 'sector_rotation', 'single_name_shock')),
    scope            TEXT        NOT NULL,                    -- 'market' | MRE group key | symbol
    state            TEXT        NOT NULL CHECK (state IN ('OPEN', 'STABILIZING', 'RECOVERING', 'CLOSED')),
    opened_at        TIMESTAMPTZ NOT NULL,
    closed_at        TIMESTAMPTZ,
    trigger          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    baseline_date    DATE        NOT NULL,                    -- last close before the first trigger day
    affected_sectors TEXT[]      NOT NULL DEFAULT '{}',       -- MRE sector-group keys
    policy_version   TEXT        NOT NULL,
    last_eval        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE market_event_episodes IS
    'Market-event episodes (lane market-event-detect). Advisory only. One open episode per kind+scope.';

CREATE UNIQUE INDEX IF NOT EXISTS market_event_episodes_one_open_idx
    ON market_event_episodes (kind, scope) WHERE state <> 'CLOSED';

CREATE TABLE IF NOT EXISTS market_event_candidates (
    episode_id      TEXT        NOT NULL REFERENCES market_event_episodes (episode_id),
    symbol          TEXT        NOT NULL,
    source          TEXT[]      NOT NULL DEFAULT '{}',        -- holding | stop_out | watchlist | sector_peer
    baseline_price  NUMERIC,
    last_price      NUMERIC,
    drawdown_pct    NUMERIC,                                  -- negative = fell
    quality_score   NUMERIC,                                  -- 0..100
    discount_score  NUMERIC,                                  -- 0..100
    rank            INTEGER,
    fell_for_reason BOOLEAN     NOT NULL DEFAULT false,
    reason_evidence JSONB       NOT NULL DEFAULT '{}'::jsonb, -- always carries sector, industry, group
    gates           JSONB       NOT NULL DEFAULT '{}'::jsonb, -- WP3
    state           TEXT        NOT NULL DEFAULT 'WATCH'
                    CHECK (state IN ('WATCH', 'STABILIZING', 'READY', 'ENTERED', 'INVALIDATED')),
    plan            JSONB,                                    -- WP3
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (episode_id, symbol)
);

COMMENT ON TABLE market_event_candidates IS
    'Re-entry candidates per market-event episode (lane market-event-detect). Advisory only; never READY without an operator star when fell_for_reason.';

CREATE INDEX IF NOT EXISTS market_event_candidates_rank_idx
    ON market_event_candidates (episode_id, rank);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'trade_ai') THEN
        GRANT SELECT, INSERT, UPDATE ON market_event_episodes TO trade_ai;
        GRANT SELECT, INSERT, UPDATE ON market_event_candidates TO trade_ai;
    END IF;
END
$$;
