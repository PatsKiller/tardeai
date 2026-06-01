# Hermes Telegram and Communication Retention Audit

**Date:** 2026-05-31
**Status:** COMPLETE — read-only audit, no changes

---

## Are Telegram Messages Stored in DB?

**Partially.** Delivery metadata is stored, but full message payloads are not.

### alert_events table

| Field | Stored? |
|-------|---------|
| telegram_message_id | YES |
| telegram_sent_at | YES |
| alert_type (24 types) | YES |
| Full message body/payload | NO |
| Retention | 30 days (SHORT tier) |

### notification_log table

| Field | Stored? |
|-------|---------|
| channel (telegram/email) | YES |
| notification_type | YES |
| subject | YES |
| body_summary | YES (truncated) |
| payload (JSONB) | YES (metadata, not full message) |
| sent_at | YES |
| status | YES |
| Retention | 30 days (SHORT tier) |

### learning_digest_delivery_log

| Field | Stored? |
|-------|---------|
| digest_id, channel, status, sent_at | YES |
| Full digest content | NO |
| Retention | 90 days (MEDIUM tier) |

**Conclusion:** Telegram message IDs and delivery status are stored, but full message text/payloads are not persisted in the database. After 30 days, even the metadata is purged.

---

## Are AI Analyst Weekly Reviews Stored?

| Script | Output | Stored in DB? | File Output? |
|--------|--------|---------------|-------------|
| portfolio_weekly_report.py | HTML report + Telegram summary | NO | YES — last 8 HTML files retained |
| strategy_weekly_review.py | Strategy performance + Telegram | NO | Partial — log only |
| portfolio_ai_analyst.py | AI portfolio analysis | NO | Log only |
| aegis_morning_brief_delivery.py | Morning brief | NO | Dedupe file + log |
| weekly_learning_digest.py | Post-trade review | delivery_log only | Log only |

**Conclusion:** Weekly reviews are NOT stored as full documents in the database. HTML reports retain the last 8 copies. Telegram-sent summaries are fire-and-forget.

---

## Can Hermes Read Historical Messages?

| Source | Hermes Readable? | Notes |
|--------|-----------------|-------|
| alert_events | YES (via hermes_readonly) | Metadata only, no message body |
| notification_log | YES (via hermes_readonly) | body_summary available, truncated |
| Weekly HTML reports | YES (file access) | Last 8 retained on disk |
| Telegram API message history | NO | Would need bot API call |
| Log files | YES (file access) | Unstructured, 1.3 GB, no index |

---

## What Redaction Rules Are Needed?

If Hermes ever reads communication history:
- Redact any account numbers, balances, or PII
- Redact broker credentials
- Redact API keys/tokens
- Mask Telegram chat IDs
- Never store raw message payloads in hermes_* tables without sanitization

---

## What Should Never Be Stored

- Telegram bot tokens
- Chat IDs (should be masked)
- Account numbers or SSN
- Broker API credentials
- Raw HTML with embedded PII
- Full message payloads without sanitization

---

## Recommended Future Design

If Hermes needs to review historical advisory messages, create (after separate approval):

**Table: `hermes_advisory_message_reviews`**

| Field | Type | Description |
|-------|------|-------------|
| id | BIGSERIAL | PK |
| message_id | TEXT | Reference to alert_events or notification_log |
| channel | TEXT | telegram / email / dashboard |
| source_agent | TEXT | aegis / portfolio_weekly / strategy_weekly |
| generated_at | TIMESTAMPTZ | Original generation time |
| message_type | TEXT | morning_brief / weekly_review / alert / digest |
| sanitized_body | TEXT | Redacted message content |
| actionability_score | REAL | 0–1 per actionability standard |
| finding_type | TEXT | From failure classes |
| backlog_required | BOOLEAN | Research backlog needed? |
| reviewed_status | TEXT | pending / reviewed / archived |
| retention_until | DATE | Auto-purge date |
| sensitive_flags_json | JSONB | What was redacted |
| source_hash | TEXT | Dedup key |

**Do NOT create this table in Phase 20.** Requires separate approval.

---

## Summary

| Question | Answer |
|----------|--------|
| Full Telegram payloads in DB? | NO |
| Delivery metadata in DB? | YES (30-day retention) |
| Weekly reviews in DB? | NO (HTML files only, last 8) |
| Hermes can read metadata? | YES |
| Hermes can read full messages? | NO (not stored) |
| Future storage recommended? | YES — hermes_advisory_message_reviews |
| Created in Phase 20? | NO — requires separate approval |
