-- ONE migration for the precompute store (LQ-20261107-2646, REVIEW-2606 F3). Two parts in one transaction:
--   part 1  the four cc_product_* tables + cc_product_seq: LQ-20261107-2591 phase 0 (a3809a0ce), VERBATIM below.
--           They are the DSN §4.2 contract; scripts/lib/cc_products/store_pg.py (2595) writes them to this DDL.
--   part 2  hermes_projection_entry / hermes_projection_meta: LQ-20261107-2595 (b), formerly
--           sql/migrations/20261112_cc_hermes_projection_tables.sql (never applied; superseded by this file).
-- Operator apply (DDL as role trade_ai; the file itself carries no SET ROLE):
--   cd /tmp && sudo -u postgres psql -d trade_ai -X -v ON_ERROR_STOP=1 -c 'SET ROLE trade_ai' -f - \
--        < <release>/migrations/2026_11_12_cc_data_products.sql
-- (superuser session: the login role is not a member of trade_ai, so a plain psql gets "permission denied to set
-- role"; the file is fed on stdin by the operator's shell, so the postgres user never needs to read the path.)
-- Rollback: 2026_11_12_cc_data_products.down.sql, same form. Every table here holds derived data only.
--
-- cc data products: the four precompute-cache tables (DSN-20261112-PRECOMPUTE-CACHE §4.2; LQ-20261107-2591, phase 0).
--
-- ADDITIVE ONLY. Four new tables and one sequence; no existing table is touched.
--   cc_product_current    one row per (product, scope): the exact bytes the server sends, plus the clocks and limits
--   cc_product_delta      per-item changes for products that declare `delta: true` (feeds `since=<seq>`)
--   cc_product_build_log  one row per build attempt, and one per sweep: the receipt and the measurement
--   cc_product_dirty      the rebuild-on-change queue (a writer inserts, then NOTIFY cc_product_dirty)
--
-- Writers (phase 0 code, not yet scheduled):
--   scripts/lib/data_products/builder.py  -> cc_product_current, cc_product_delta, cc_product_build_log, cc_product_dirty (drain)
--   scripts/lib/data_products/sweeper.py  -> DELETE per config/data_products.yaml, one SWEEP row in cc_product_build_log
-- Readers: none yet. Phase 1 adds the product route (§6.1).
--
-- The clocks live in the row, not only in the body, so the sweeper and the freshness watchdog read them by column.
-- `as_of` is when the data was true (the oldest source watermark); the sweeper purges on `as_of`, not `built_at`
-- (a rebuild of unchanged, old data must not look young).
--
-- DO NOT APPLY THIS FILE FROM AN ENGINE LANE. The operator applies it (command in READY-LQ-20261107-2591).
-- DDL must run as role trade_ai.
BEGIN;

CREATE SEQUENCE IF NOT EXISTS cc_product_seq;

CREATE TABLE IF NOT EXISTS cc_product_current (
    product_id         text        NOT NULL,
    scope_key          text        NOT NULL DEFAULT 'global',
    body               bytea       NOT NULL,          -- ready-to-send JSON bytes; the server never re-serialises
    body_gz            bytea,                         -- gzip of body; NULL for small bodies
    etag               text        NOT NULL,          -- content hash of body
    seq                bigint      NOT NULL,          -- nextval('cc_product_seq') at the write that changed body
    as_of              timestamptz NOT NULL,          -- when the data was true (oldest source watermark)
    built_at           timestamptz NOT NULL,          -- when the builder finished the build that produced body
    checked_at         timestamptz NOT NULL,          -- last build that found body unchanged (or built it)
    next_refresh_at    timestamptz,
    stale_after_s      integer     NOT NULL,
    hard_expiry_s      integer     NOT NULL,
    purge_after_s      integer     NOT NULL,
    status             text        NOT NULL DEFAULT 'OK',
    reason             text,
    source_watermarks  jsonb       NOT NULL DEFAULT '{}'::jsonb,
    builder_sha        text,
    schema_version     integer     NOT NULL DEFAULT 1,
    bytes              integer     NOT NULL,
    build_ms           integer,
    PRIMARY KEY (product_id, scope_key),
    CONSTRAINT cc_product_current_status_ck CHECK (status IN ('OK', 'DEGRADED')),
    CONSTRAINT cc_product_current_limits_ck CHECK (
        stale_after_s > 0 AND hard_expiry_s >= stale_after_s AND purge_after_s >= hard_expiry_s),
    CONSTRAINT cc_product_current_bytes_ck CHECK (bytes = octet_length(body))
);

-- the sweeper's purge scan and the freshness watchdog
CREATE INDEX IF NOT EXISTS cc_product_current_as_of_idx ON cc_product_current (as_of);

CREATE TABLE IF NOT EXISTS cc_product_delta (
    product_id  text        NOT NULL,
    scope_key   text        NOT NULL DEFAULT 'global',
    seq         bigint      NOT NULL,
    op          text        NOT NULL,
    item_id     text        NOT NULL,
    item        jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (product_id, scope_key, seq),
    CONSTRAINT cc_product_delta_op_ck CHECK (op IN ('upsert', 'remove')),
    CONSTRAINT cc_product_delta_item_ck CHECK ((op = 'remove') OR (item IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS cc_product_delta_created_idx ON cc_product_delta (created_at);

CREATE TABLE IF NOT EXISTS cc_product_build_log (
    id             bigserial   PRIMARY KEY,
    lane           text        NOT NULL,
    product_id     text        NOT NULL,              -- '__sweep__' for a dp-sweeper run
    scope_key      text        NOT NULL DEFAULT 'global',
    started_at     timestamptz NOT NULL,
    finished_at    timestamptz NOT NULL,
    outcome        text        NOT NULL,
    build_ms       integer,
    peak_rss_kb    bigint,
    rows_read      bigint,
    bytes_written  bigint,
    error          text,
    detail         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT cc_product_build_log_outcome_ck CHECK (outcome IN (
        'BUILT', 'UNCHANGED', 'FAILED', 'SKIPPED_BUSY', 'REFUSED_SIZE', 'REFUSED_MEMORY', 'OVERRUN',
        'SWEEP_OK', 'SWEEP_FAILED'))
);

CREATE INDEX IF NOT EXISTS cc_product_build_log_product_idx ON cc_product_build_log (product_id, scope_key, started_at DESC);
CREATE INDEX IF NOT EXISTS cc_product_build_log_started_idx ON cc_product_build_log (started_at);

CREATE TABLE IF NOT EXISTS cc_product_dirty (
    product_id    text        NOT NULL,
    scope_key     text        NOT NULL DEFAULT 'global',
    reason        text        NOT NULL,
    requested_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (product_id, scope_key)
);

COMMENT ON TABLE cc_product_current IS 'DSN-20261112-PRECOMPUTE-CACHE §4.2: one row per product and scope; writer scripts/lib/data_products/builder.py; purged by dp-sweeper';
COMMENT ON TABLE cc_product_delta IS 'DSN-20261112-PRECOMPUTE-CACHE §4.2: per-item deltas for delta products; newest 2000 per scope and <= 24 h kept';
COMMENT ON TABLE cc_product_build_log IS 'DSN-20261112-PRECOMPUTE-CACHE §4.2: one row per build attempt / sweep; 7 d and <= 200000 rows kept';
COMMENT ON TABLE cc_product_dirty IS 'DSN-20261112-PRECOMPUTE-CACHE §5.3: rebuild-on-change queue; > 1 h is an alert, > 24 h deleted';

-- ---------------------------------------------------------------------------------------------------------------
-- part 2 (LQ-20261107-2595 b): the Hermes research projection as an indexed table. DSN §4.3 / §4.5.
-- Writer: scripts/lib/cc_products/hermes_projection.py (ingest). One table keyed by (map, entry_key) replaces the
-- DSN's separate plan and symbol tables: one row per entry of the four projection maps; the plan and symbol access
-- paths are the two indexes.

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
