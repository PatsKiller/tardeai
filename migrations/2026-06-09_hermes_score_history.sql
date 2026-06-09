-- 2026-06-09_hermes_score_history.sql — append-only score snapshots (H-4 calibration + H-5 alerting). Additive.
CREATE TABLE IF NOT EXISTS hermes_score_history (
    id              BIGSERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    composite_score NUMERIC,
    rank            INT,
    components      JSONB,
    price           NUMERIC,
    scored_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hsh_symbol_time ON hermes_score_history (symbol, scored_at DESC);

-- Weight-calibration suggestions (H-4) — advisory; operator applies to config/hermes_score_weights.yaml.
CREATE TABLE IF NOT EXISTS hermes_weight_calibration (
    id              BIGSERIAL PRIMARY KEY,
    factor          TEXT NOT NULL,
    current_weight  NUMERIC,
    suggested_weight NUMERIC,
    predictiveness  NUMERIC,          -- correlation of factor score with forward return
    sample_n        INT,
    rationale       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
