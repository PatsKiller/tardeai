-- Market Outlook Engine v1 — the record and its grades (LQ-20261107-966, design FABLE-OUTLOOK-METHODOLOGY-LQ-946 §4.6).
--
-- ADDITIVE ONLY. Two new tables, no existing table touched. Single writer each:
--   market_outlook_records -> scripts/lib/writers/market_outlook_writer.py
--   market_outlook_grades  -> same module, write_grades()
-- A record is immutable: record_id is the primary key and the writer uses ON CONFLICT (record_id) DO NOTHING, so
-- corrections are new records whose JSON `supersedes` names the one they replace.
--
-- The authoritative copy of the evaluation is the `record` jsonb (MarketOutlookRecord@v1, field names are a contract
-- with the brief builder). The scalar columns are a denormalised index for the API and for `select ... order by as_of`.
-- DO NOT APPLY THIS FILE FROM AN ENGINE LANE: the lead applies it through the release.
BEGIN;

CREATE TABLE IF NOT EXISTS market_outlook_records (
    record_id        text PRIMARY KEY,
    as_of            timestamptz NOT NULL,
    mode             text NOT NULL CHECK (mode IN ('sunday', 'monday', 'daily', 'event')),
    score            numeric(6, 2),
    band             text CHECK (band IN ('RISK_OFF', 'DEFENSIVE', 'NEUTRAL', 'RISK_ON')),
    confidence       numeric(6, 4) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    confidence_band  text CHECK (confidence_band IN ('LOW', 'MODERATE', 'HIGH')),
    policy_version   text NOT NULL,
    engine_commit    text NOT NULL DEFAULT '',
    record           jsonb NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    -- a score without a band (or a band without a score) is a broken record, not a state
    CONSTRAINT market_outlook_records_score_band_ck CHECK ((score IS NULL) = (band IS NULL)),
    CONSTRAINT market_outlook_records_receipt_ck CHECK (record->>'record_id' = record_id)
);

CREATE INDEX IF NOT EXISTS market_outlook_records_as_of_idx
    ON market_outlook_records (as_of DESC);
CREATE INDEX IF NOT EXISTS market_outlook_records_mode_as_of_idx
    ON market_outlook_records (mode, as_of DESC);

CREATE TABLE IF NOT EXISTS market_outlook_grades (
    record_id     text PRIMARY KEY REFERENCES market_outlook_records (record_id),
    week_ending   date NOT NULL,
    realized      jsonb,
    scenario_hit  text CHECK (scenario_hit IN ('base', 'bull', 'bear')),
    brier         numeric(6, 4) CHECK (brier IS NULL OR (brier >= 0 AND brier <= 1)),
    level_hits    jsonb,
    band_hit      boolean,
    status        text NOT NULL CHECK (status IN ('pending', 'graded', 'unavailable')),
    payload       jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS market_outlook_grades_week_idx
    ON market_outlook_grades (week_ending DESC);

COMMIT;
