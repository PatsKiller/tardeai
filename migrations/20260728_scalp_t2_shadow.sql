-- M3 P3 — T2 (moomoo L2 depth) SHADOW comparison table.
--
-- Records what the data tier WOULD have been for an armed symbol/minute if real
-- order-book depth were allowed to drive scoring, alongside the T0 values actually
-- used. scalp_ignition_events is deliberately NOT touched: it keeps writing
-- data_tier='T0' / dcf=0.4, so gates, sizing and the permission queue are unchanged
-- while this collects evidence.
--
-- Promotion to live scoring (dcf 0.4 -> 1.0, assumed slippage 40 -> 8 bps) is a
-- separate, explicit operator decision — see docs/operations/MOOMOO_T2_SHADOW.md.
-- The T2 metrics module warns that displayed depth understates true size, so depth
-- may only ever SIZE DOWN; that is the question this table exists to answer.

CREATE TABLE IF NOT EXISTS scalp_t2_shadow (
    id                  BIGSERIAL PRIMARY KEY,
    session_date        DATE        NOT NULL,
    symbol              TEXT        NOT NULL,
    minute_of_session   INTEGER,
    observed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- what actually drove scoring this minute
    live_data_tier      TEXT        NOT NULL DEFAULT 'T0',
    live_dcf            NUMERIC,
    t0_spread_bps       NUMERIC,          -- spread the T0 path inferred from bars

    -- real depth (NULL when unarmed / OpenD down / not entitled)
    t2_available        BOOLEAN     NOT NULL DEFAULT false,
    t2_spread_bps       NUMERIC,          -- quoted spread from the actual book
    t2_book_imbalance   NUMERIC,          -- [-1,+1]; +1 = all size on the bid
    t2_microprice       NUMERIC,
    t2_bid_depth        NUMERIC,
    t2_ask_depth        NUMERIC,
    t2_levels           INTEGER,
    t2_entitlement      TEXT,
    t2_feed             TEXT,

    -- counterfactual: what the tier/confidence WOULD have been
    would_be_tier       TEXT,
    would_be_dcf        NUMERIC,
    would_be_slip_bps   NUMERIC,

    -- why T2 was unavailable, when it was not
    unavailable_reason  TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per symbol/minute; re-runs of the intraday logger update in place.
CREATE UNIQUE INDEX IF NOT EXISTS scalp_t2_shadow_uniq
    ON scalp_t2_shadow (session_date, symbol, minute_of_session);

CREATE INDEX IF NOT EXISTS scalp_t2_shadow_session_idx
    ON scalp_t2_shadow (session_date DESC, t2_available);

COMMENT ON TABLE scalp_t2_shadow IS
    'SHADOW ONLY. T2/L2 depth observations + counterfactual tier vs the T0 values that '
    'actually drove scoring. Never read by gates, sizing, or the order path.';
