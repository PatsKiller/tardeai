-- Down migration for 2026_11_08_market_outlook.sql — DROP only, and only the two tables that migration created.
-- Never run against a database whose market_outlook_records may hold evaluations that were never mirrored to the
-- runtime JSON (data/runtime/market_outlook/): export them first. AGENTS.md rail 6 (never delete) applies to data;
-- this file exists so a failed release can be unwound before any record exists.
BEGIN;
DROP TABLE IF EXISTS market_outlook_grades;
DROP TABLE IF EXISTS market_outlook_records;
COMMIT;
