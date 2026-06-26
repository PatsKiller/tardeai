-- Unify live-submit path tagging on paper_trade_proposals (queue-route vs canary pilot).
ALTER TABLE paper_trade_proposals
  ADD COLUMN IF NOT EXISTS live_submit_path TEXT,
  ADD COLUMN IF NOT EXISTS last_correlation_id UUID;

COMMENT ON COLUMN paper_trade_proposals.live_submit_path IS
  'Which execution surface submitted/routed this row: queue_route_2fa | canary_pilot | paper_auto | record_only';
COMMENT ON COLUMN paper_trade_proposals.last_correlation_id IS
  'Last broker intent correlation_id for audit trail across submit paths';

-- Normalize legacy lowercase expired status on trade proposals.
UPDATE paper_trade_proposals
   SET status = 'EXPIRED', updated_at = NOW()
 WHERE lower(status) = 'expired' AND status <> 'EXPIRED';