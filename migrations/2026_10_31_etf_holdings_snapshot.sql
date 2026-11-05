-- etf_holdings_snapshot: top holdings of held/watched ETFs (single writer scripts/lib/writers/etf_holdings_writer.py).
-- §7A row proposed in PR #2333; applied only after that row is granted. Idempotent.
CREATE TABLE IF NOT EXISTS etf_holdings_snapshot (
    etf      TEXT        NOT NULL,
    holding  TEXT        NOT NULL,
    name     TEXT,
    weight   NUMERIC     NOT NULL,
    as_of    TIMESTAMPTZ NOT NULL,
    source   TEXT        NOT NULL,
    PRIMARY KEY (etf, holding, as_of)
);
CREATE INDEX IF NOT EXISTS etf_holdings_snapshot_etf_asof ON etf_holdings_snapshot (etf, as_of DESC);
