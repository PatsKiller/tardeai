-- InstrumentRecord@v1: additive projection fields on the existing canonical
-- watchlist row. No historical evidence is rewritten.
ALTER TABLE watchlist_items
  ADD COLUMN IF NOT EXISTS instrument_record JSONB,
  ADD COLUMN IF NOT EXISTS instrument_record_updated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS watchlist_items_instrument_record_entity_idx
  ON watchlist_items ((instrument_record->>'canonical_entity_id'));
CREATE INDEX IF NOT EXISTS watchlist_items_instrument_record_workflow_idx
  ON watchlist_items ((instrument_record->>'workflow_id'));
