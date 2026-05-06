-- Session 18d: Run label lineage for auto proposals

ALTER TABLE auto_proposal_runs
ADD COLUMN IF NOT EXISTS execution_label TEXT,
ADD COLUMN IF NOT EXISTS source_run_label TEXT;

ALTER TABLE auto_proposal_decisions
ADD COLUMN IF NOT EXISTS execution_label TEXT,
ADD COLUMN IF NOT EXISTS source_run_label TEXT;

ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS source_run_label TEXT,
ADD COLUMN IF NOT EXISTS auto_execution_label TEXT;
