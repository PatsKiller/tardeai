-- 2026-08-13_two_way_curation_p0_surfaced_by.sql
-- Expand watch_directive_hits.surfaced_by so desk sources keep honest provenance
-- instead of collapsing to 'hermes'. Additive only.
--
-- Allowed: trade_ai | hermes | operator | cio | advisory | defense

BEGIN;

ALTER TABLE watch_directive_hits
    DROP CONSTRAINT IF EXISTS watch_directive_hits_surfaced_by_check;

ALTER TABLE watch_directive_hits
    ADD CONSTRAINT watch_directive_hits_surfaced_by_check
    CHECK (surfaced_by = ANY (ARRAY[
        'trade_ai'::text,
        'hermes'::text,
        'operator'::text,
        'cio'::text,
        'advisory'::text,
        'defense'::text
    ]));

COMMIT;
