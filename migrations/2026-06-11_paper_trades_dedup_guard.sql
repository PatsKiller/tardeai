-- Dedup guard for paper_trades: prevents the race/retry double-insert that created the NUVL duplicate
-- (two 'open' rows 0.67s apart, only one carrying the broker_order_id). DB-level so it protects every
-- insert path without touching the order pipeline. Reversible: DROP TRIGGER + DROP FUNCTION.
CREATE OR REPLACE FUNCTION paper_trades_dedup_guard() RETURNS trigger AS $$
DECLARE existing_id BIGINT;
BEGIN
  -- only guard newly-opened positions; never interfere with closed/cancelled imports or exits
  IF COALESCE(NEW.lifecycle_state, 'open') <> 'open' THEN
    RETURN NEW;
  END IF;

  -- (1) exact same broker order already recorded -> true duplicate of the same fill
  IF COALESCE(NEW.broker_order_id, '') <> '' THEN
    SELECT id INTO existing_id FROM paper_trades
      WHERE broker_order_id = NEW.broker_order_id LIMIT 1;
    IF existing_id IS NOT NULL THEN
      RETURN NULL;   -- suppress
    END IF;
  END IF;

  -- (2) near-duplicate open row (race/retry): same symbol + account + shares, both open, within 15s
  SELECT id INTO existing_id FROM paper_trades
    WHERE symbol = NEW.symbol
      AND target_account IS NOT DISTINCT FROM NEW.target_account
      AND shares = NEW.shares
      AND lifecycle_state = 'open'
      AND created_at > NOW() - INTERVAL '15 seconds'
    ORDER BY created_at LIMIT 1;
  IF existing_id IS NOT NULL THEN
    -- if the incoming row carries the broker_order_id the existing one lacks, backfill the survivor
    IF COALESCE(NEW.broker_order_id, '') <> '' THEN
      UPDATE paper_trades
         SET broker_order_id = NEW.broker_order_id,
             filled_at       = COALESCE(filled_at, NEW.filled_at),
             entry_price     = NEW.entry_price,
             entry_time      = COALESCE(entry_time, NEW.entry_time, NEW.filled_at),
             broker_status   = COALESCE(NEW.broker_status, broker_status),
             -- the incoming row is the authoritative post-submit record: promote pending -> its status
             status          = CASE WHEN status = 'pending' THEN COALESCE(NEW.status, status) ELSE status END,
             lifecycle_state = CASE WHEN lifecycle_state = 'open' THEN COALESCE(NEW.lifecycle_state, lifecycle_state) ELSE lifecycle_state END
       WHERE id = existing_id AND COALESCE(broker_order_id, '') = '';
    END IF;
    RETURN NULL;   -- suppress the duplicate insert
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_paper_trades_dedup ON paper_trades;
CREATE TRIGGER trg_paper_trades_dedup BEFORE INSERT ON paper_trades
  FOR EACH ROW EXECUTE FUNCTION paper_trades_dedup_guard();
