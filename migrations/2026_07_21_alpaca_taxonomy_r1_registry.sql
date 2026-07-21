-- R1: Alpaca multi-account taxonomy — registry columns + interlock parity log
-- Safe: additive. Does NOT drop legacy accounts table.

-- ── broker_accounts columns ─────────────────────────────────────────────────
ALTER TABLE broker_accounts
  ADD COLUMN IF NOT EXISTS credential_slot TEXT,
  ADD COLUMN IF NOT EXISTS notes TEXT,
  ADD COLUMN IF NOT EXISTS live_arm_token TEXT;

-- is_enabled already exists; expose synonym comment only (no second boolean)

-- environment enum guard (allow existing import/paper/live)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'broker_accounts_environment_chk'
  ) THEN
    ALTER TABLE broker_accounts
      ADD CONSTRAINT broker_accounts_environment_chk
      CHECK (environment IN ('paper', 'live', 'import'));
  END IF;
END $$;

-- Structural refuse: Alpaca LIVE cannot be is_enabled without live_arm_token.
-- Schwab/Fidelity grandfathered (broker <> 'alpaca').
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'broker_accounts_alpaca_live_arm_chk'
  ) THEN
    ALTER TABLE broker_accounts
      ADD CONSTRAINT broker_accounts_alpaca_live_arm_chk
      CHECK (
        broker <> 'alpaca'
        OR environment <> 'live'
        OR is_enabled IS NOT TRUE
        OR (live_arm_token IS NOT NULL AND length(trim(live_arm_token)) > 0)
      );
  END IF;
END $$;

-- Paper Alpaca credential slot stamp
UPDATE broker_accounts
   SET credential_slot = COALESCE(credential_slot, 'ALPACA_PAPER'),
       notes = COALESCE(notes, 'Alpaca paper training (tradeai_automated)')
 WHERE account_key = 'tradeai_automated';

-- Fidelity: ACATS 07-16 moved rollover assets to Schwab; keep import row as historical
-- lineage (DISABLED). Operator may retire later — NO delete in R1 without confirm.
UPDATE broker_accounts
   SET notes = COALESCE(notes,
       'Historical/import after ACATS 2026-07-16 — assets now at schwab_rollover_ira; no live Fidelity holdings in holdings.json'),
       is_enabled = false
 WHERE account_key = 'fidelity_rollover_ira';

UPDATE account_automation_policies aap
   SET automation_mode = 'DISABLED',
       approval_policy = 'PROPOSAL_ONLY',
       source = 'r1_taxonomy',
       updated_at = now()
 FROM broker_accounts ba
 WHERE aap.account_id = ba.id AND ba.account_key = 'fidelity_rollover_ira';

-- Interlock parity log
CREATE TABLE IF NOT EXISTS interlock_parity_log (
  id BIGSERIAL PRIMARY KEY,
  account TEXT NOT NULL,
  canonical_answer TEXT,          -- paper | live | unknown
  legacy_answer TEXT,
  agreed BOOLEAN NOT NULL,
  caller TEXT,
  action TEXT,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_interlock_parity_log_ts ON interlock_parity_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_interlock_parity_log_disagree
  ON interlock_parity_log (created_at DESC) WHERE agreed = false;
