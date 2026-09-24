-- Subject identity on watch rows (M5 Module 1, item 1c).
-- Additive only; nullable; the backfill is a separate, dry-run-first script
-- (scripts/backfill_watch_subject_guid.py).
--
-- M5 audit 2026-09-23: neither watch_directives nor watchlist_items had any
-- GUID column, so the null rate of subject_guid on watch rows was 100% by
-- construction. watch_directives_writer already resolved the GUID but could
-- only carry it on its in-memory receipt ("the table has no identity column").
--
--   subject_guid  registry subject GUID (identity_registry, resolve_guid-walked)
--   issuer_guid   issuer GUID when the registry / spine knows the issuer
--
-- watch_directives_writer probes for these columns before writing them, so the
-- code may ship before this is applied.

ALTER TABLE watch_directives
    ADD COLUMN IF NOT EXISTS subject_guid UUID,
    ADD COLUMN IF NOT EXISTS issuer_guid  UUID;

ALTER TABLE watchlist_items
    ADD COLUMN IF NOT EXISTS subject_guid UUID,
    ADD COLUMN IF NOT EXISTS issuer_guid  UUID;

CREATE INDEX IF NOT EXISTS watch_directives_subject_guid_idx
    ON watch_directives (subject_guid) WHERE subject_guid IS NOT NULL;
CREATE INDEX IF NOT EXISTS watchlist_items_subject_guid_idx
    ON watchlist_items (subject_guid) WHERE subject_guid IS NOT NULL;
