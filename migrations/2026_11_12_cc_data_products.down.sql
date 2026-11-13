-- LQ-20261107-2646: also drops part 2 (hermes_projection_*). The projection JSON file stays the source of record.
-- Down migration for 2026_11_12_cc_data_products.sql: DROP only what that migration created.
-- The four tables hold derived data only (every row is rebuilt from its sources by the builder), so dropping them
-- loses no record of truth. Still: run only to unwind a failed release, and export cc_product_build_log first if
-- it is needed as evidence (AGENTS.md rail 6, never delete).
BEGIN;
DROP TABLE IF EXISTS hermes_projection_meta;
DROP TABLE IF EXISTS hermes_projection_entry;
DROP TABLE IF EXISTS cc_product_dirty;
DROP TABLE IF EXISTS cc_product_build_log;
DROP TABLE IF EXISTS cc_product_delta;
DROP TABLE IF EXISTS cc_product_current;
DROP SEQUENCE IF EXISTS cc_product_seq;
COMMIT;
