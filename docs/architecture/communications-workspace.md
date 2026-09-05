# Communications Workspace — Phase 7

**Status:** Communications Gateway program documentation (Phases 0–11).
**Date:** 2026-09-05

**Route:** `/v3/communications`  
**UI:** `apps/command-center-v3/src/pages/CommunicationsHub.tsx`  
**Portal:** `scripts/communications_portal.py`  
**API:** `/api/v2/communications/*` (wired in `scripts/api_v2.py`)

## Purpose

Single operator source-of-truth page over CommunicationEvent ledger projections,
ChannelDelivery stubs, and subject/thread memory. **Read-only.** The page and
portal never call Telegram, Slack, or other providers.

## Endpoints

| Method | Path | Handler |
|---|---|---|
| GET | `/api/v2/communications/health` | `health()` |
| GET | `/api/v2/communications/events` | `list_events(limit, subject_key, status)` |
| GET | `/api/v2/communications/events/<event_id>` | `get_event(event_id)` |
| GET | `/api/v2/communications/deliveries` | `list_deliveries(event_id)` |
| GET | `/api/v2/communications/subjects` | `list_subjects(limit)` |

Responses include `source: "memory" | "db" | "empty"`. Empty ledgers return honest
empty lists — never provider scrapes.

## Delivery ownership banner

`health().delivery_owned` is always `false` while gateway mode is OFF/SHADOW
(Phase 1–7). The UI banner states:

> Ledger-backed · gateway does not own delivery while OFF/SHADOW

## UI tabs

1. **Live / Events** — table + detail panel  
2. **Deliveries** — ChannelDelivery@v1 rows (RESERVED stubs OK)  
3. **Subjects / Threads** — subject memory projections  
4. **Retention** — placeholder `retention_class` counts (no librarian purge)  
5. **Agent consumption** — placeholder for Phase 8  

## Tests

`tests/test_communications_portal.py` — empty/health/memory list/get filters;
asserts portal source text does not import provider senders.