# Hermes Phase 37C — Recommended Low-Latency Bridge Architecture

**Date:** 2026-06-01
**Status:** COMPLETE — design only

---

## Architecture

```
Hermes writes staged research row
    ↓ (application code or DB trigger)
hermes_advisory_events queue table (INSERT)
    ↓ (optional PG LISTEN/NOTIFY for instant wake)
Bridge Worker (lightweight Python service or timer)
    ↓ reads event, refreshes target
Advisory context cache refresh (llm_intelligence_cache or advisory metadata)
    ↓
Trade AI LLM context builder sees fresh advisory on next call
```

## Queue Table: hermes_advisory_events (Future)

| Column | Type | Description |
|--------|------|-------------|
| id | BIGSERIAL | PK |
| event_type | TEXT | research_staged, research_promoted, embedding_completed, backlog_created |
| source_table | TEXT | hermes_research_intelligence, content_embeddings, etc. |
| source_id | BIGINT | Row ID that triggered event |
| created_at | TIMESTAMPTZ | Event creation time |
| processed_at | TIMESTAMPTZ | When worker processed this |
| processed_status | TEXT | pending / processing / completed / failed / skipped |
| worker_id | TEXT | Which worker instance processed |
| latency_ms | INTEGER | Time from created to processed |
| error_message | TEXT | If failed |

## Bridge Worker

- Type: systemd user service (always-on) or oneshot timer (every 30 sec)
- Reads: hermes_advisory_events WHERE processed_status = 'pending'
- Writes: llm_intelligence_cache advisory refresh ONLY (or marks event processed)
- **Never writes**: proposals, trades, journal, holdings, broker
- Kill switch: hermes_sidecar/.hermes/BRIDGE_DISABLED
- Rate limit: max 10 events per minute
- Dead letter: after 3 failures, mark 'failed', alert via log

## LISTEN/NOTIFY (Optional Enhancement)

```sql
-- Trigger on hermes_research_intelligence INSERT
CREATE OR REPLACE FUNCTION hermes_notify_new_research() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('hermes_new_research', NEW.id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

Worker listens on `hermes_new_research` channel for instant wake. Falls back to polling every 30 sec if connection drops.

## Fallback Timer

If worker is down, a fallback systemd timer runs every 5 minutes to process any unprocessed events.

## Dashboard Visibility

- Queue depth: count of pending events
- Last processed: timestamp
- Average latency: avg(latency_ms)
- Failed events: count
- Worker status: active/stopped

---

## Safety Boundaries

The bridge worker MUST NOT:
- Write to proposals, trades, journal, holdings
- Access broker APIs
- Create embeddings (separate workflow)
- Promote without operator approval (only refresh existing promoted sections)
- Send external messages
- Modify other services

The bridge worker MAY:
- Refresh llm_intelligence_cache sections for already-promoted Hermes rows
- Update advisory metadata timestamps
- Log processed events
- Write to hermes_advisory_events (processed_status only)
