-- Agent Lifecycle: requirements intake for DEFINE stage
CREATE TABLE IF NOT EXISTS agent_requirements (
    id                  BIGSERIAL PRIMARY KEY,
    agent_name          TEXT NOT NULL,
    use_case            TEXT NOT NULL,
    expected_output     TEXT NOT NULL,
    failure_conditions  TEXT NOT NULL,
    acceptance_criteria TEXT NOT NULL,
    stage               TEXT NOT NULL DEFAULT 'define',
    status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','retired')),
    created_by          TEXT NOT NULL DEFAULT 'operator',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_requirements_agent ON agent_requirements(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_requirements_status ON agent_requirements(status);
