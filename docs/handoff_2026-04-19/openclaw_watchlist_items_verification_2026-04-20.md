# Market Intelligence — watchlist_items Verification Report

**Date:** 2026-04-20
**Verifier:** Claude Opus 4.6
**Files changed:** `linux_port_v2/linux/db_setup_advisor.sql`, `scripts/db_adapter.py`, `scripts/portfolio_server.py`

---

## 1. Schema

```sql
CREATE TABLE IF NOT EXISTS watchlist_items (
    id serial PRIMARY KEY,
    symbol varchar(20) NOT NULL,
    source_type varchar(20) NOT NULL,
    thesis text,
    target_intent varchar(30),
    added_date date NOT NULL,
    added_by varchar(30) NOT NULL,
    confidence numeric(3,2),
    status varchar(20) DEFAULT 'active',
    notes text,
    data jsonb,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    UNIQUE(symbol, source_type)
);
```

## 2. db_adapter Helpers

- `save_watchlist_item(item)` — upsert by (symbol, source_type)
- `remove_watchlist_item(symbol, source_type)` — sets status='removed'
- `load_watchlist_items(source_type, status)` — query by source/status

## 3. Server API Endpoints

- `GET /api/watchlist/read` — returns current watchlist.json contents
- `POST /api/watchlist/write` — add/remove watchlist items with dual-write to JSON + Postgres

## 4. Evidence

### Backfill
All 12 existing watchlist.json entries backfilled to Postgres:
```
ARCC, AXON, BWXT, GD, HII, HTGC, JEPI, MAIN, MSFT, NVDA, PLTR, VCIT
```

### Add test
```bash
curl -X POST /api/watchlist/write -d '{"action":"add","symbol":"AAPL","thesis":"Testing"}'
→ {"ok": true, "action": "added", "symbol": "AAPL"}
Postgres: AAPL | growth | 2026-04-20 | active
```

### Remove test
```bash
curl -X POST /api/watchlist/write -d '{"action":"remove","symbol":"AAPL"}'
→ {"ok": true, "action": "removed", "symbol": "AAPL"}
Postgres: AAPL | status: removed (soft delete)
```

### JSON + Postgres consistency
- JSON: AAPL removed from watchlist.json
- Postgres: AAPL status set to 'removed' (preserved for history)

## 5. Command Center Modal

**DEFERRED to separate UI task.** The API endpoints are ready. The modal will call `POST /api/watchlist/write` when built. Current watchlist display in CC still reads `watchlist.json` directly (unchanged behavior).

## 6. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| watchlist_items table created | **PASS** |
| Existing entries backfilled to Postgres | **PASS** (12 items) |
| API add works (JSON + Postgres dual-write) | **PASS** |
| API remove works (JSON remove + Postgres soft-delete) | **PASS** |
| Existing watchlist.json behavior preserved | **PASS** |
| Supports future source_types (ai_generated, analyst_curated) | **PASS** (schema ready) |
| CC modal implemented | **DEFERRED** (API ready, UI is separate task) |
