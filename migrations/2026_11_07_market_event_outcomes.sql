-- LQ-20261107-339 (WP6, SPEC_MARKET_EVENT_REENTRY_20261107 4.7) -- what happened to a candidate AFTER each signal.
--
-- One row per (episode, symbol, signal). signal is baseline | READY_t1 | READY_t2 | READY_t3. signal_at and price are
-- written once (ON CONFLICT DO NOTHING in the scorer) so a later re-score can never move the entry. ret_5/20/60 are
-- percent returns of the Nth session close after the signal's anchor session versus `price`; NULL means NOT YET
-- OBSERVABLE (horizon not reached, or no Finviz close for that session) and is never a zero.
--
--   signal_basis  plan_stamp = the tranche stamp WP3 wrote into market_event_candidates.plan; first_seen = the
--                 scorer saw state READY with no stamp and recorded its own observation time.
-- Rollback: migrations/2026_11_07_market_event_outcomes.down.sql.

CREATE TABLE IF NOT EXISTS market_event_outcomes (
    episode_id     text        NOT NULL,
    symbol         text        NOT NULL,
    signal         text        NOT NULL CHECK (signal IN ('baseline','READY_t1','READY_t2','READY_t3')),
    signal_at      timestamptz NOT NULL,
    anchor_session date        NOT NULL,
    price          numeric     NOT NULL,
    price_source   text        NOT NULL,
    signal_basis   text        NOT NULL DEFAULT 'plan_stamp' CHECK (signal_basis IN ('plan_stamp','first_seen','baseline_close')),
    ret_5          numeric,
    ret_20         numeric,
    ret_60         numeric,
    scored_at      timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (episode_id, symbol, signal)
);
CREATE INDEX IF NOT EXISTS market_event_outcomes_episode_idx ON market_event_outcomes (episode_id, signal);
COMMENT ON COLUMN market_event_outcomes.ret_5 IS 'Percent return of the 5th session close after anchor_session vs price. NULL = not yet observable, never 0.';
