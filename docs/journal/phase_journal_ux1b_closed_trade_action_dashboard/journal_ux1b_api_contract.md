# JOURNAL-UX-1B — API Contract

All endpoints are **read-only**. No mutations, no secrets, no trading actions.

## GET /api/v2/journal/closed-trades/action-dashboard

Daily summary with best/worst trade, top lesson, action queue.

## GET /api/v2/journal/closed-trades/action-items

Action items sorted by priority (urgent > high > medium > low).

## GET /api/v2/journal/closed-trades/lessons

Per-trade lessons with improved_lesson, rule_feedback, confidence_delta.

## Rules

- Read-only
- human_review_only on all items
- No secrets, credentials, or chat IDs
- No mutations
