-- OPERATOR REVIEW/APPLY ONLY (AGENTS §17): existing store trade_transactions; adds one NULLABLE column, no new
-- authority, no writer, no backfill and no data change.
--
-- Why (2026-11-04, PR #2556 identity work): the recovery engine had no stable identity for a transaction. The composite
-- dedupe_key is date|action|symbol|QUANTITY|account|uid, so a quantity correction necessarily produces a different key
-- and the engine saw a second sale (80 -> 82 became -200 -> -400 while the case still reported complete, no gaps).
-- provider_uid is the broker's own immutable reference for the event, and it is the ONLY stable identity this source
-- has.
--
-- NULL is a FACT, not a missing value: it means the provider supplied no reference for that row. The recovery reader
-- reports such a row as UNRESOLVED rather than guessing an identity from date, price, arrival or the composite. The
-- write side (both ingesters) is a separate change under its own grant; this migration only makes the column exist.
--
-- Idempotent. Never run from a lane or a test. No default: a default would manufacture an identity that does not exist.
BEGIN;
ALTER TABLE trade_transactions ADD COLUMN IF NOT EXISTS provider_uid text;
COMMENT ON COLUMN trade_transactions.provider_uid IS
  'The provider''s own immutable event reference (SnapTrade activity id / Schwab order-activity id). NULL = the '
  'provider supplied none; readers must treat NULL as UNRESOLVED identity and must not reconstruct it from '
  'dedupe_key, date, price or arrival order.';
COMMIT;
