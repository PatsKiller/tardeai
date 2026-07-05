-- ALPACA-OPTIONS Stage 2 (Part D): Alpaca paper lifecycle states + audit meta
-- on options_approval_queue. Additive + idempotent.
--
-- Schema finding (verified live 2026-07-05): options_approval_queue.status is
-- plain TEXT with NO existing CHECK/enum — writers use 'pending'/'blocked'
-- (sync_approval_queue), 'approved'/'rejected' (resolve_approval), and
-- 'executed' is preserved by sync's ON CONFLICT CASE. So "extend the CHECK"
-- means ADD one, covering the legacy set plus the new Alpaca lane:
--
--   pending/approved ──operator --mark-ready──▶ READY_FOR_ALPACA_PAPER
--   READY_FOR_ALPACA_PAPER ──executor --submit --confirm──▶ ALPACA_PAPER_SUBMITTED
--   ALPACA_PAPER_SUBMITTED ──reconcile──▶ ALPACA_PAPER_FILLED | ALPACA_PAPER_REJECTED
--   ALPACA_PAPER_FILLED ──reconcile close-detection──▶ ALPACA_PAPER_CLOSED
--   ALPACA_PAPER_CLOSED ──record_outcome──▶ OUTCOME_RECORDED
--   OUTCOME_RECORDED ──operator only, NEVER automatic──▶ READY_FOR_LIVE_REVIEW
--
-- meta jsonb carries the full order audit (meta.alpaca_json: request/response/
-- readback/fill/close) written by scripts/lib/options_pipeline/alpaca_paper.py.

ALTER TABLE options_approval_queue
    ADD COLUMN IF NOT EXISTS meta JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE options_approval_queue
    DROP CONSTRAINT IF EXISTS options_approval_queue_status_chk;

ALTER TABLE options_approval_queue
    ADD CONSTRAINT options_approval_queue_status_chk CHECK (status IN (
        -- legacy desk review lane (unchanged)
        'pending', 'blocked', 'approved', 'rejected', 'executed',
        -- Alpaca paper lane (Stage 2)
        'READY_FOR_ALPACA_PAPER',
        'ALPACA_PAPER_SUBMITTED',
        'ALPACA_PAPER_FILLED',
        'ALPACA_PAPER_REJECTED',
        'ALPACA_PAPER_CLOSED',
        'OUTCOME_RECORDED',
        'READY_FOR_LIVE_REVIEW'
    ));

-- Guard rail: sync_approval_queue's ON CONFLICT only preserves
-- 'approved'/'rejected'/'executed' — a re-scanned proposal_id would clobber an
-- in-flight Alpaca state back to 'pending'/'blocked'. Protect the lane at the
-- schema level (BEFORE UPDATE keeps the old status; sync's other column
-- updates still apply).
CREATE OR REPLACE FUNCTION options_queue_protect_alpaca_states()
RETURNS trigger AS $$
BEGIN
    IF OLD.status IN ('READY_FOR_ALPACA_PAPER', 'ALPACA_PAPER_SUBMITTED',
                      'ALPACA_PAPER_FILLED', 'ALPACA_PAPER_REJECTED',
                      'ALPACA_PAPER_CLOSED', 'OUTCOME_RECORDED',
                      'READY_FOR_LIVE_REVIEW')
       AND NEW.status IN ('pending', 'blocked') THEN
        NEW.status := OLD.status;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_oaq_protect_alpaca_states ON options_approval_queue;

CREATE TRIGGER trg_oaq_protect_alpaca_states
    BEFORE UPDATE ON options_approval_queue
    FOR EACH ROW EXECUTE FUNCTION options_queue_protect_alpaca_states();
