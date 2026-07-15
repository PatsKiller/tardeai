-- Transfer-aware position provenance + rollover/Roth-ladder audit trail
-- Holdings SSOT remains holdings.json; these tables persist transfer history,
-- source tracking, and automatic normalizations for performance continuity.

CREATE TABLE IF NOT EXISTS position_transfer_history (
    id                  SERIAL PRIMARY KEY,
    event_id            TEXT NOT NULL UNIQUE,
    symbol              TEXT NOT NULL,
    from_account        TEXT NOT NULL,
    to_account          TEXT NOT NULL,
    shares_moved        NUMERIC NOT NULL,
    cost_basis_total    NUMERIC,
    per_share_basis     NUMERIC,
    basis_source        TEXT,
    transfer_type       TEXT NOT NULL DEFAULT 'internal_transfer',
    -- fidelity_to_schwab | traditional_to_roth | external_rollover | internal_transfer | other
    confidence          TEXT NOT NULL DEFAULT 'medium',
    -- high | medium | low
    status              TEXT NOT NULL DEFAULT 'detected',
    -- detected | auto_normalized | needs_review | confirmed | dismissed
    share_match_pct     NUMERIC,
    performance_adjusted BOOLEAN NOT NULL DEFAULT TRUE,
    detected_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    normalized_at       TIMESTAMPTZ,
    sync_source         TEXT,
    notes               TEXT,
    meta_json           JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_pos_xfer_hist_symbol
    ON position_transfer_history (symbol, detected_at DESC);
CREATE INDEX IF NOT EXISTS ix_pos_xfer_hist_to_acct
    ON position_transfer_history (to_account, symbol);
CREATE INDEX IF NOT EXISTS ix_pos_xfer_hist_from_acct
    ON position_transfer_history (from_account, symbol);
CREATE INDEX IF NOT EXISTS ix_pos_xfer_hist_status
    ON position_transfer_history (status, detected_at DESC);
CREATE INDEX IF NOT EXISTS ix_pos_xfer_hist_type
    ON position_transfer_history (transfer_type, detected_at DESC);

CREATE TABLE IF NOT EXISTS position_normalization_log (
    id                  SERIAL PRIMARY KEY,
    event_id            TEXT,
    symbol              TEXT NOT NULL,
    from_account        TEXT,
    to_account          TEXT NOT NULL,
    shares_moved        NUMERIC,
    action              TEXT NOT NULL,
    -- auto_normalize | basis_carry_forward | account_update | stop_impact_flag | manual_confirm
    previous_state      JSONB,
    new_state           JSONB,
    stop_impact_json    JSONB,
    performance_note    TEXT,
    actor               TEXT NOT NULL DEFAULT 'system',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_pos_norm_log_symbol
    ON position_normalization_log (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_pos_norm_log_event
    ON position_normalization_log (event_id);

COMMENT ON TABLE position_transfer_history IS
  'Cross-account share movements (Fidelity→Schwab rollover, Trad IRA→Roth ladder, etc.). '
  'Used for provenance, performance continuity, and operator transparency.';
COMMENT ON TABLE position_normalization_log IS
  'Immutable audit of automatic/manual position normalizations after transfers.';

-- Operator-facing notifications for known transfer seasons / active rollovers
CREATE TABLE IF NOT EXISTS position_transfer_notifications (
    id                  SERIAL PRIMARY KEY,
    kind                TEXT NOT NULL,
    -- rollover_active | roth_ladder_season | normalization_batch | partial_arrival
    title               TEXT NOT NULL,
    body                TEXT NOT NULL,
    severity            TEXT NOT NULL DEFAULT 'info',
    -- info | warning
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    related_event_ids   TEXT[] DEFAULT '{}',
    meta_json           JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ,
    dismissed_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_pos_xfer_notif_active
    ON position_transfer_notifications (active, created_at DESC)
    WHERE active = TRUE AND dismissed_at IS NULL;
