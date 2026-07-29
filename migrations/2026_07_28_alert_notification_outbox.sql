-- Trade AI Telegram notification normalization v2 — occurrence-based model.
-- Additive only. No broker, order, 2FA, or guardrail table is modified.
-- NOT APPLIED TO PRODUCTION. Verified up/down/up on an isolated container only.
--
-- Why this replaced the first draft
-- ---------------------------------
-- The first draft keyed everything on ONE row per fingerprint:
--     CREATE UNIQUE INDEX ... ON alert_notification_events (fingerprint);
--     INSERT ... ON CONFLICT (fingerprint) DO UPDATE SET payload = EXCLUDED.payload
-- That made a fingerprint both the IDENTITY of a condition and its LIFETIME dedupe
-- key, with two consequences:
--   1. the first occurrence suppressed every later one forever — a stop that went
--      unprotected, was fixed, and went unprotected again a week later notified once;
--   2. each repeat overwrote the stored payload, destroying occurrence history.
--
-- The model below separates the three things that draft conflated:
--   alert_incidents    the recurring CONDITION (correlation + current state)
--   alert_occurrences  each immutable OBSERVATION of it, with its notify decision
--   ..._deliveries     each delivery ATTEMPT for an occurrence
--
-- Recurrence works because the uniqueness constraint is PARTIAL: at most one OPEN
-- incident per dedupe_key. Resolve it and the same condition may legitimately open a
-- new incident later. Nothing is ever overwritten.

-- ── Incidents: the recurring condition ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_incidents (
    incident_id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL,                 -- fingerprint: identity, NOT a lifetime lock
    alert_type TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_producer TEXT,
    account_id TEXT,
    symbol TEXT,                              -- representative; see alert_occurrences for the set
    correlation_key TEXT,                     -- account + detection cycle, for batching
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','expired')),
    severity TEXT NOT NULL DEFAULT 'info',
    operator_action_required BOOLEAN NOT NULL DEFAULT FALSE,
    operator_action_type TEXT,
    state_version TEXT NOT NULL DEFAULT '1',
    route_mode TEXT CHECK (route_mode IS NULL OR route_mode IN ('IMMEDIATE','DIGEST','COMMAND_CENTER','LOG')),
    logical_destination TEXT,
    digest_bucket TEXT CHECK (digest_bucket IS NULL OR digest_bucket IN ('RISK','TRADING','OPS')),
    policy_version TEXT,
    environment TEXT NOT NULL DEFAULT 'production',
    synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    delivery_prohibited BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_notified_at TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by TEXT,
    resolved_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    occurrence_count INTEGER NOT NULL DEFAULT 0,
    notified_count INTEGER NOT NULL DEFAULT 0,
    suppressed_count INTEGER NOT NULL DEFAULT 0
);

-- THE constraint that makes recurrence possible: only one OPEN incident per
-- condition. A resolved incident does not block a later one.
CREATE UNIQUE INDEX IF NOT EXISTS alert_incidents_open_dedupe_uq
    ON alert_incidents (dedupe_key)
    WHERE status = 'open';
-- Batching: sibling observations in one account/detection cycle join one incident.
CREATE UNIQUE INDEX IF NOT EXISTS alert_incidents_open_correlation_uq
    ON alert_incidents (correlation_key)
    WHERE status = 'open' AND correlation_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS alert_incidents_open_idx
    ON alert_incidents (last_seen_at DESC) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS alert_incidents_type_idx
    ON alert_incidents (alert_type, status, last_seen_at DESC);

-- ── Occurrences: immutable observations. Append-only; never UPDATEd. ─────────
CREATE TABLE IF NOT EXISTS alert_occurrences (
    occurrence_id BIGSERIAL PRIMARY KEY,
    alert_id TEXT UNIQUE NOT NULL,            -- stable handle used in deep links
    incident_id TEXT NOT NULL REFERENCES alert_incidents(incident_id) ON DELETE CASCADE,
    occurrence_seq INTEGER NOT NULL,
    dedupe_key TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,         -- injected/explicit: deterministic dedupe
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    alert_type TEXT NOT NULL,
    source_producer TEXT,
    symbol TEXT,
    severity TEXT NOT NULL DEFAULT 'info',
    operator_action_required BOOLEAN NOT NULL DEFAULT FALSE,
    state_version TEXT NOT NULL DEFAULT '1',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,        -- immutable history
    payload_redaction_level TEXT NOT NULL DEFAULT 'operator_safe',
    -- should_notify() decision, persisted with its inputs so it can be audited later
    notify BOOLEAN NOT NULL,
    decision_reason TEXT NOT NULL,
    is_escalation BOOLEAN NOT NULL DEFAULT FALSE,
    is_resolution BOOLEAN NOT NULL DEFAULT FALSE,
    is_material_transition BOOLEAN NOT NULL DEFAULT FALSE,
    suppressed_until TIMESTAMPTZ,
    decision_inputs JSONB NOT NULL DEFAULT '{}'::jsonb, -- prior-state snapshot
    route_mode TEXT,
    logical_destination TEXT,
    digest_bucket TEXT,
    runtime_mode TEXT,
    UNIQUE (incident_id, occurrence_seq)
);

CREATE INDEX IF NOT EXISTS alert_occurrences_incident_idx
    ON alert_occurrences (incident_id, occurrence_seq DESC);
CREATE INDEX IF NOT EXISTS alert_occurrences_dedupe_idx
    ON alert_occurrences (dedupe_key, observed_at DESC);
CREATE INDEX IF NOT EXISTS alert_occurrences_pending_immediate_idx
    ON alert_occurrences (observed_at)
    WHERE notify AND route_mode = 'IMMEDIATE';

-- ── Delivery attempts: one row per ATTEMPT, scoped to an occurrence ──────────
-- The first draft had UNIQUE(logical_destination, message_fingerprint) WHERE sent,
-- which made the audit trail lossy: the same rendered message could only ever be
-- recorded once, so a legitimate recurrence could not be audited.
CREATE TABLE IF NOT EXISTS alert_notification_deliveries (
    id BIGSERIAL PRIMARY KEY,
    occurrence_id BIGINT REFERENCES alert_occurrences(occurrence_id) ON DELETE CASCADE,
    alert_id TEXT,
    incident_id TEXT,
    attempt_seq INTEGER NOT NULL DEFAULT 1,
    logical_destination TEXT,
    route_mode TEXT NOT NULL,
    delivery_status TEXT NOT NULL
        CHECK (delivery_status IN ('queued','claimed','sent','failed','suppressed','abandoned')),
    delivery_reason TEXT,
    telegram_message_id TEXT,
    message_fingerprint TEXT,
    rendered_message TEXT,
    claimed_by TEXT,
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (occurrence_id, attempt_seq)
);

-- One SENT delivery per occurrence: idempotent under concurrent workers, while
-- still allowing many attempts and a full audit of each.
CREATE UNIQUE INDEX IF NOT EXISTS alert_deliveries_one_sent_per_occurrence_uq
    ON alert_notification_deliveries (occurrence_id)
    WHERE delivery_status = 'sent';
CREATE INDEX IF NOT EXISTS alert_deliveries_claimable_idx
    ON alert_notification_deliveries (created_at)
    WHERE delivery_status IN ('queued','failed');

-- ── Digest membership ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_digest_queue (
    id BIGSERIAL PRIMARY KEY,
    occurrence_id BIGINT REFERENCES alert_occurrences(occurrence_id) ON DELETE CASCADE,
    alert_id TEXT,
    incident_id TEXT,
    digest_bucket TEXT NOT NULL CHECK (digest_bucket IN ('RISK','TRADING','OPS')),
    queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at TIMESTAMPTZ,
    claimed_by TEXT,
    included_at TIMESTAMPTZ,                  -- set ONLY after successful delivery
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '24 hours'),
    summary_group TEXT,
    synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(occurrence_id, digest_bucket)
);

CREATE INDEX IF NOT EXISTS alert_digest_queue_pending_idx
    ON alert_digest_queue(digest_bucket, queued_at)
    WHERE included_at IS NULL;

-- ── Preferences + audit (unchanged shape) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS operator_alert_preferences (
    alert_type TEXT PRIMARY KEY,
    general_telegram TEXT NOT NULL CHECK (general_telegram IN ('OFF','IMMEDIATE','DIGEST')),
    approval_telegram TEXT NOT NULL CHECK (approval_telegram IN ('OFF','IMMEDIATE')),
    command_center BOOLEAN NOT NULL DEFAULT TRUE,
    digest_bucket TEXT NOT NULL CHECK (digest_bucket IN ('RISK','TRADING','OPS')),
    ttl_seconds INTEGER NOT NULL,
    dedupe_window_seconds INTEGER NOT NULL,
    escalate_after_seconds INTEGER,
    sound_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    policy_version TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT NOT NULL DEFAULT 'system',
    last_delivery_at TIMESTAMPTZ,
    last_suppression_reason TEXT
);

CREATE TABLE IF NOT EXISTS operator_alert_preference_audit (
    id BIGSERIAL PRIMARY KEY,
    alert_type TEXT NOT NULL,
    old_value JSONB,
    new_value JSONB NOT NULL,
    changed_by TEXT NOT NULL,
    change_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Compatibility view: prior code reads alert_notification_events ───────────
-- Presents the latest occurrence joined to its incident, so existing readers keep
-- working without resurrecting the one-row-per-fingerprint model underneath.
CREATE OR REPLACE VIEW alert_notification_events AS
SELECT
    o.occurrence_id            AS id,
    o.alert_id,
    o.alert_type,
    i.source_system,
    o.source_producer,
    i.account_id,
    o.symbol,
    o.severity,
    o.operator_action_required,
    i.operator_action_type,
    o.logical_destination,
    o.route_mode,
    o.digest_bucket,
    o.incident_id,
    o.dedupe_key               AS fingerprint,
    o.state_version,
    o.payload,
    i.policy_version,
    o.observed_at              AS created_at,
    i.last_seen_at             AS updated_at,
    i.expires_at,
    i.resolved_at,
    i.acknowledged_at,
    CASE WHEN o.notify THEN NULL ELSE o.decision_reason END AS suppression_reason,
    i.notified_count           AS delivery_count,
    i.suppressed_count         AS duplicate_count,
    i.synthetic,
    i.environment,
    i.delivery_prohibited
FROM alert_occurrences o
JOIN alert_incidents i ON i.incident_id = o.incident_id;

CREATE OR REPLACE VIEW v_active_command_center_alerts AS
SELECT * FROM alert_notification_events
WHERE resolved_at IS NULL
  AND created_at >= now() - INTERVAL '7 days'
  AND (expires_at IS NULL OR expires_at > now())
  AND route_mode IN ('IMMEDIATE','DIGEST','COMMAND_CENTER');
