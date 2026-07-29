-- SL-S2 2026-07-29: alert_notification_events did not expose last_delivery_status /
-- last_delivery_at, but alert_outbox.active_alerts() selects both, so
-- GET /api/v3/alerts/active returned 500 the moment the migration was applied.
--
-- Cause: alert_outbox.py was written against the FIRST draft schema, where
-- alert_notification_events was a TABLE carrying these columns. The migration was
-- then rewritten into the three-table occurrence model with this name becoming a
-- derived VIEW, and the consumer was not fully updated. Additive fix: surface the
-- latest delivery per occurrence via LATERAL. Read path only.
--
-- NOT FIXED HERE: alert_outbox.py:269 still runs
--   UPDATE alert_notification_events SET last_delivery_status=... 
-- against this view. A join view is not auto-updatable, so that write will fail if
-- ever reached. It is currently unreachable (runtime mode OFF returns on the LEGACY
-- path before the outbox is touched). Tracked separately — do not treat this view
-- change as having repaired the delivery path.
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
    i.delivery_prohibited,
    d.delivery_status          AS last_delivery_status,
    COALESCE(d.completed_at, d.created_at) AS last_delivery_at
FROM alert_occurrences o
JOIN alert_incidents i ON i.incident_id = o.incident_id
LEFT JOIN LATERAL (
    SELECT delivery_status, completed_at, created_at
      FROM alert_notification_deliveries dd
     WHERE dd.occurrence_id = o.occurrence_id
     ORDER BY dd.attempt_seq DESC, dd.id DESC
     LIMIT 1
) d ON true;
