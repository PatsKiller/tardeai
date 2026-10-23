"""Shared SQL predicate for counting substantive, unrecovered pipeline failures."""

# Keep health scoring and automated diagnosis aligned. Empty ``errors`` arrays are
# bookkeeping/termination rows, not failures that should trigger another producer run.
SUBSTANTIVE_FAILURE_FILTER = """NOT (
    f.summary IS NOT NULL AND (
        f.summary::text ~ '"errors"\\s*:\\s*\\[\\s*\\]'
        OR COALESCE(f.summary::jsonb->>'errors', 'x') IN ('', '[]')
        OR (jsonb_typeof(f.summary::jsonb->'errors') = 'array'
            AND jsonb_array_length(f.summary::jsonb->'errors') = 0)
    )
)"""
