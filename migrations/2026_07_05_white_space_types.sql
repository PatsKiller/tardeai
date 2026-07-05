-- White-Space Discovery (Stage 1): additive candidate-type expansion.
--
-- Widens the hermes_discovery_candidates.candidate_type CHECK constraint to
-- admit the White-Space Discovery candidate families. ADDITIVE ONLY: every
-- previously valid type remains valid, no rows are touched, no defaults
-- change. The drop+add runs as ONE ALTER TABLE statement so the swap is
-- atomic (no window where the column is unconstrained).
--
-- New types:
--   STRATEGY_CANDIDATE                trading-strategy white-space candidates
--   PRIVATE_COMPANY_PROXY_CANDIDATE   public proxies for private companies
--   LEGAL_TOPIC_CANDIDATE             legal research topics (advisory-only)
--   CASE_LAW_CANDIDATE                court decisions / case-law findings
--   STATUTE_UPDATE_CANDIDATE          statute / regulation change trackers
--   WEBSITE_CONTENT_CANDIDATE         website/article content briefs
--   GAP_CANDIDATE                     coverage-gap findings. The MISSING_*
--                                     family is NOT 10 separate types: each
--                                     gap carries meta_json.gap_type (e.g.
--                                     missing_stop, missing_research,
--                                     missing_source, missing_domain, ...)
--                                     on a single GAP_CANDIDATE row.
--
-- Mirrored in scripts/lib/hermes_discovery/inbox.py CANDIDATE_TYPES.

ALTER TABLE hermes_discovery_candidates
    DROP CONSTRAINT hermes_discovery_candidates_candidate_type_check,
    ADD CONSTRAINT hermes_discovery_candidates_candidate_type_check CHECK (candidate_type IN (
        'SOURCE_CANDIDATE', 'TREND_CANDIDATE', 'TICKER_CANDIDATE',
        'TOPIC_CANDIDATE', 'CONNECTOR_CANDIDATE',
        'STRATEGY_CANDIDATE', 'PRIVATE_COMPANY_PROXY_CANDIDATE',
        'LEGAL_TOPIC_CANDIDATE', 'CASE_LAW_CANDIDATE',
        'STATUTE_UPDATE_CANDIDATE', 'WEBSITE_CONTENT_CANDIDATE',
        'GAP_CANDIDATE'));
