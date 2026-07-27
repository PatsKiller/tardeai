-- Active Trader Stage 3 · 0006 rejection + notification enrichment (up)
-- Additive columns required by the Stage 3 classifier/notification/fallback models.

ALTER TABLE broker_rejection_events
    ADD COLUMN occurrence_count      INTEGER NOT NULL DEFAULT 1 CHECK (occurrence_count >= 1),
    ADD COLUMN idempotency_key       TEXT UNIQUE,
    ADD COLUMN classifier_version    TEXT,
    ADD COLUMN matched_rule_id       TEXT,
    ADD COLUMN confidence            TEXT CHECK (confidence IN ('EXACT_CODE','MESSAGE_PATTERN','STRUCTURAL','FALLBACK')),
    ADD COLUMN notification_state    TEXT NOT NULL DEFAULT 'NONE'
        CHECK (notification_state IN ('NONE','CREATED','UPDATED','ACKNOWLEDGED','RESOLVED','EXPIRED')),
    ADD COLUMN fallback_state        TEXT NOT NULL DEFAULT 'NOT_EVALUATED'
        CHECK (fallback_state IN ('NOT_EVALUATED','AUTO_FAILOVER_ELIGIBLE','PROMPT_OPERATOR',
                                  'REAUTHORIZE_SESSION','WAIT_FOR_SOURCE_FINALITY','NO_FALLBACK','BLOCKED')),
    ADD COLUMN capability_evidence_ref TEXT;

ALTER TABLE active_trader_notification_events
    ADD COLUMN dedupe_key            TEXT,
    ADD COLUMN rejection_event_id    UUID,
    ADD COLUMN status                TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN','UPDATED','ESCALATED','ACKNOWLEDGED','RESOLVED','EXPIRED')),
    ADD COLUMN escalated_at          TIMESTAMPTZ,
    ADD COLUMN resolved_at           TIMESTAMPTZ,
    ADD COLUMN expires_at            TIMESTAMPTZ;

CREATE UNIQUE INDEX idx_at_notifications_dedupe
    ON active_trader_notification_events (dedupe_key)
    WHERE dedupe_key IS NOT NULL AND status IN ('OPEN','UPDATED','ESCALATED');
