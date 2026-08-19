-- Seed watchlist social/research source-health rows (2026-08-19 watchlist audit, Gap A/E).
--
-- report_source() only ever UPDATEs data_source_health (never INSERTs), so a missing row
-- makes liveness silently drop. The watchlist lanes now report the following keys:
--   sync_social_to_intelligence.py        -> 'social'
--   hermes_social_sentiment.py            -> 'hermes_social'
--   research_watchlist_discovery.py       -> 'research_discovery'
--   candidate_discovery_orchestrator.py   -> 'social_scalp' + 'yahoo_movers' (+ existing
--                                            'news_catalyst' / 'incubator' from 20260509)
-- Seed every key so the health agent can see these lanes go stale and auto-remediate.

INSERT INTO data_source_health (source_key, status, max_stale_minutes) VALUES
    ('social',             'unknown', 1440),
    ('hermes_social',      'unknown', 1440),
    ('research_discovery', 'unknown', 1440),
    ('social_scalp',       'unknown', 1440),
    ('yahoo_movers',       'unknown', 1440)
ON CONFLICT (source_key) DO NOTHING;
