-- Active Trader Stage 3 · 0006 rejection + notification enrichment (down)
DROP INDEX IF EXISTS idx_at_notifications_dedupe;
ALTER TABLE active_trader_notification_events
    DROP COLUMN IF EXISTS expires_at,
    DROP COLUMN IF EXISTS resolved_at,
    DROP COLUMN IF EXISTS escalated_at,
    DROP COLUMN IF EXISTS status,
    DROP COLUMN IF EXISTS rejection_event_id,
    DROP COLUMN IF EXISTS dedupe_key;
ALTER TABLE broker_rejection_events
    DROP COLUMN IF EXISTS capability_evidence_ref,
    DROP COLUMN IF EXISTS fallback_state,
    DROP COLUMN IF EXISTS notification_state,
    DROP COLUMN IF EXISTS confidence,
    DROP COLUMN IF EXISTS matched_rule_id,
    DROP COLUMN IF EXISTS classifier_version,
    DROP COLUMN IF EXISTS idempotency_key,
    DROP COLUMN IF EXISTS occurrence_count;
