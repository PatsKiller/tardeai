-- Event-sourced proposal funnel: statuses were overwritten post-execution making the funnel unauditable
-- (47/55 trades linked to proposals yet only 1 showed APPROVED). Trigger captures every transition.
CREATE TABLE IF NOT EXISTS proposal_status_events (
    id BIGSERIAL PRIMARY KEY,
    proposal_id BIGINT NOT NULL,
    symbol TEXT,
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pse_prop ON proposal_status_events (proposal_id, changed_at);

CREATE OR REPLACE FUNCTION proposal_status_event_fn() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO proposal_status_events (proposal_id, symbol, old_status, new_status)
    VALUES (NEW.id, NEW.symbol, NULL, NEW.status);
  ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
    INSERT INTO proposal_status_events (proposal_id, symbol, old_status, new_status)
    VALUES (NEW.id, NEW.symbol, OLD.status, NEW.status);
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_proposal_status_events ON paper_trade_proposals;
CREATE TRIGGER trg_proposal_status_events
  AFTER INSERT OR UPDATE OF status ON paper_trade_proposals
  FOR EACH ROW EXECUTE FUNCTION proposal_status_event_fn();
