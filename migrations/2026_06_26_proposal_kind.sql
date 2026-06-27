-- Unify protection adjustments into the proposals queue: type discriminator + source link.
ALTER TABLE paper_trade_proposals ADD COLUMN IF NOT EXISTS proposal_kind TEXT DEFAULT 'entry';
ALTER TABLE paper_trade_proposals ADD COLUMN IF NOT EXISTS protection_source_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_ptp_kind_status ON paper_trade_proposals (proposal_kind, status);
-- backfill existing rows explicitly as entries (safety: the ATM entry path will filter on this)
UPDATE paper_trade_proposals SET proposal_kind='entry' WHERE proposal_kind IS NULL;
