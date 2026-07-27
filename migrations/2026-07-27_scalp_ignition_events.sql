-- M3-S3: shadow ignition-event log (Momentum Scalp Signal Engine, design §11).
-- SHADOW: compute everything, log everything, EMIT NOTHING (no alerts, no proposals).
-- Structurally isolated — NO foreign key / reference to paper_trade_proposals or any order path.
-- Outcome columns (mfe/mae/hit_1r_*) are backfilled T+1 by the separate M3-S4 job.

CREATE TABLE IF NOT EXISTS scalp_ignition_events (
    id                 BIGSERIAL   PRIMARY KEY,
    symbol             TEXT        NOT NULL,
    fired_at           TIMESTAMPTZ NOT NULL,
    session_date       DATE        NOT NULL,
    minute_of_session  SMALLINT,
    lane               TEXT        NOT NULL,   -- 'IGN_45'|'IGN_60'|'IGN_ACCEL'|'IGN_75'|'BELOW'
    ign_score          NUMERIC(6,2) NOT NULL,
    subscores          JSONB       NOT NULL,   -- v_rvol,v_burst,v_cat,v_disp,v_liq,v_rs
    rvol_tod           NUMERIC(10,2),
    profile_source     TEXT,                   -- 'per_symbol' | 'universe_proxy' | 'none'
    data_tier          TEXT        NOT NULL,   -- 'T0'|'T1'|'T2'
    dcf                NUMERIC(3,2) NOT NULL,
    data_age_sec       INT,
    -- T0 microstructure (from scalp_t0_metrics)
    spread_bps         NUMERIC(10,2),
    spread_source      TEXT,                   -- 'corwin_schultz'|'abdi_ranaldo'|'max_cs_ar'
    pressure           NUMERIC(6,3),           -- bar_pressure ∈ [-1,1]
    evr                NUMERIC(10,4),
    amihud_illiq       NUMERIC(20,12),
    -- hypothetical trade reference (NOT an order)
    entry_ref          NUMERIC(12,4),
    stop_ref           NUMERIC(12,4),
    r_dollars          NUMERIC(12,4),
    stop_dist_bps      NUMERIC(10,2),
    -- gate outcome (shadow VETO/PASS record; never authorizes anything)
    gate_result        TEXT,                   -- 'PASS'|'VETO'|null
    gate_reasons       JSONB,
    -- outcomes, backfilled T+1 (M3-S4)
    mfe_5m   NUMERIC(10,4),  mae_5m   NUMERIC(10,4),
    mfe_15m  NUMERIC(10,4),  mae_15m  NUMERIC(10,4),
    mfe_30m  NUMERIC(10,4),  mae_30m  NUMERIC(10,4),
    r_multiple_30m     NUMERIC(10,4),
    hit_1r_first       BOOLEAN,                -- reached +1R before -1R
    time_to_1r_sec     INT,
    outcome_filled_at  TIMESTAMPTZ,
    engine_version     TEXT        NOT NULL DEFAULT 'm3-s3',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sie_session ON scalp_ignition_events (session_date, lane);
CREATE INDEX IF NOT EXISTS idx_sie_symbol  ON scalp_ignition_events (symbol, fired_at DESC);
CREATE INDEX IF NOT EXISTS idx_sie_pending ON scalp_ignition_events (fired_at) WHERE outcome_filled_at IS NULL;
