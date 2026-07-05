-- Cloud dual-consensus approval verdicts (ADVISORY ONLY).
-- Grok + ChatGPT free-OAuth lanes each review a qualifying broker proposal via the existing
-- cloud_review path; both-AGREE => CLOUD_APPROVE, any split/CAUTION/lane-failure => ESCALATED
-- (fail-closed), insufficient trade context => BLOCKED_INFO. This table records verdicts only —
-- NO proposal status is ever changed by this pipeline; per-order 2FA and all gates untouched.
-- Additive-only, IF NOT EXISTS throughout.

CREATE TABLE IF NOT EXISTS cloud_consensus_verdicts (
    id BIGSERIAL PRIMARY KEY,
    proposal_id BIGINT NOT NULL,
    grok_verdict TEXT,
    grok_note TEXT,
    chatgpt_verdict TEXT,
    chatgpt_note TEXT,
    consensus TEXT NOT NULL CHECK (consensus IN ('CLOUD_APPROVE', 'ESCALATED', 'BLOCKED_INFO')),
    qualified_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cloud_consensus_verdicts_proposal_id
    ON cloud_consensus_verdicts (proposal_id);
