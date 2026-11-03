-- Recovery & Re-Entry Engine — piece A (operator directive 2026-11-03)
-- One row per symbol × account × exit cluster. Additive only: no DROP, no rewrite of an existing table.
-- A confirmed stop or loss exit opens a case; a residual that is not a material fraction of the pre-exit position does
-- not count as "held" (SPCX kept 200 of ~1,000 shares and the old path declared it held, killing every re-entry).
CREATE TABLE IF NOT EXISTS recovery_cases (
    case_key            TEXT PRIMARY KEY,
    symbol              TEXT NOT NULL,
    account             TEXT NOT NULL,
    broker              TEXT,
    cluster_key         TEXT NOT NULL,
    exits_json          TEXT NOT NULL,
    exit_first_date     DATE,
    exit_last_date      DATE,
    realized_pnl        NUMERIC,
    pre_exit_shares     NUMERIC,
    residual_shares     NUMERIC,
    pre_exit_weight_pct NUMERIC,
    materiality_tier    TEXT NOT NULL CHECK (materiality_tier IN ('T1', 'T2', 'T3')),
    residual_is_held    BOOLEAN NOT NULL,
    held_reason         TEXT,
    state               TEXT NOT NULL CHECK (state IN ('STOPPED_OUT','WATCHING','RECOVERING','RE_ENTRY_READY',
                                                      'RE_ENTERED','CLOSED','SNOOZED')),
    state_since         TIMESTAMPTZ NOT NULL,
    eligibility_json    JSONB NOT NULL,
    plan_json           JSONB,
    last_nudge_at       TIMESTAMPTZ,
    last_p1_at          TIMESTAMPTZ,
    operator_decision   TEXT NOT NULL DEFAULT 'none'
                        CHECK (operator_decision IN ('none','watching','re-entered','closed','snoozed')),
    operator_note       TEXT,
    opened_at           TIMESTAMPTZ NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL,
    as_of               TIMESTAMPTZ,
    source              TEXT
);
CREATE INDEX IF NOT EXISTS recovery_cases_symbol_idx ON recovery_cases (symbol, account);
CREATE INDEX IF NOT EXISTS recovery_cases_state_idx ON recovery_cases (state, materiality_tier);
COMMENT ON TABLE recovery_cases IS
 'Recovery & Re-Entry Engine cases (operator directive 2026-11-03). Opened from confirmed loss/stop exits; the row is '
 'the single truth every surface reads. No order path touches this table.';
