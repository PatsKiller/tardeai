-- LQ-20261107-2595 phase 2 (b): the Hermes research projection as an indexed table.
-- DSN-20261112-PRECOMPUTE-CACHE §4.3 / §4.5. Writer: scripts/lib/cc_products/hermes_projection.py (ingest).
-- NOT applied by the agent. Production apply is an operator command:
--   psql -h /var/run/postgresql -d trade_ai -v ON_ERROR_STOP=1 -f sql/migrations/20261112_cc_hermes_projection_tables.sql
-- DDL in trade_ai must run as role trade_ai. Idempotent (IF NOT EXISTS throughout).
--
-- One table keyed by (map, entry_key) replaces the DSN's separate plan and symbol tables: one row per entry of the
-- four projection maps; the plan and symbol access paths are the two indexes. See the module docstring.

SET ROLE trade_ai;

BEGIN;

CREATE TABLE IF NOT EXISTS hermes_projection_entry (
    map         text        NOT NULL
                CHECK (map IN ('by_research_id', 'by_plan_id', 'by_fingerprint_open', 'by_fingerprint_completed')),
    entry_key   text        NOT NULL,
    body        jsonb       NOT NULL,
    plan_id     text        NULL,
    symbol      text        NULL,
    ingest_seq  bigint      NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (map, entry_key)
);

CREATE INDEX IF NOT EXISTS hermes_projection_entry_plan_id_idx ON hermes_projection_entry (plan_id);
CREATE INDEX IF NOT EXISTS hermes_projection_entry_upper_symbol_idx ON hermes_projection_entry (upper(symbol));

-- Single row (id = 1): which source file the entries came from. Written in the same transaction as the entries.
CREATE TABLE IF NOT EXISTS hermes_projection_meta (
    id                     smallint         PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    source_path            text             NOT NULL,
    source_mtime           double precision NOT NULL,  -- os.stat().st_mtime, epoch seconds
    source_size            bigint           NOT NULL,
    source_sha256          text             NOT NULL,
    projection_updated_ts  text             NULL,      -- the file's own updated_ts, verbatim
    ingest_seq             bigint           NOT NULL,
    entries                jsonb            NOT NULL,  -- {"by_research_id": n, ...}
    ingested_at            timestamptz      NOT NULL,
    build_ms               integer          NOT NULL
);

COMMENT ON TABLE hermes_projection_entry IS
    'LQ-2595: one row per entry of data/cio/hermes_research_projection.json maps; written only by cc_products.hermes_projection.ingest';
COMMENT ON TABLE hermes_projection_meta IS
    'LQ-2595: single-row ingest watermark for hermes_projection_entry';

COMMIT;

RESET ROLE;

-- Rollback (operator; the projection JSON file stays the source of record, so nothing is lost):
--   SET ROLE trade_ai;
--   BEGIN;
--   DROP TABLE IF EXISTS hermes_projection_meta;
--   DROP TABLE IF EXISTS hermes_projection_entry;
--   COMMIT;
--   RESET ROLE;
