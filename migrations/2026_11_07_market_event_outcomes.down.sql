-- Rollback of migrations/2026_11_07_market_event_outcomes.sql (LQ-20261107-339). Drops the scorer's own table only.
DROP TABLE IF EXISTS market_event_outcomes;
