# Analyst-Curated Watchlist Support — Verification Report

**Date:** 2026-04-21
**Verifier:** Claude Opus 4.6
**Files changed:** `scripts/portfolio_server.py`, `reports/command_center.html`

---

## 1. API Changes

### `/api/watchlist/write`
- Now accepts `source_type` param: `'user'` (default) or `'analyst_curated'`
- User entries: dual-write to JSON + Postgres (existing behavior)
- Analyst-curated entries: Postgres only (JSON remains user-watchlist-only)
- Supports optional `analyst_source` and `curation_note` in request body → stored in JSONB `data`
- Remove respects `source_type` parameter

### `/api/watchlist/read`
- Returns `items` (user entries from JSON) + `analyst_curated` (from Postgres)
- Date objects serialized for JSON compatibility

## 2. CC Modal Changes

- Added source-type dropdown: "User" or "Analyst Curated"
- Badge colors: blue "user" / gold "analyst"
- Remove button passes correct `source_type` per entry
- Both user and analyst items visible in same modal

## 3. End-to-End Flow

### Add analyst-curated
```
POST /api/watchlist/write {"action":"add", "symbol":"CRWD", "source_type":"analyst_curated",
  "thesis":"CrowdStrike — cybersecurity leader, upgraded by Goldman",
  "analyst_source":"Goldman Sachs"}
→ {"ok": true, "source_type": "analyst_curated"}

Postgres: CRWD | analyst_curated | growth | active | analyst curated | {"analyst_source": "Goldman Sachs"}
JSON: CRWD NOT in watchlist.json (correct — JSON is user-only)
```

### Read multi-source
```
GET /api/watchlist/read
→ {"items": {12 user entries}, "analyst_curated": [{symbol: "CRWD", ...}]}
```

### Remove analyst-curated
```
POST /api/watchlist/write {"action":"remove", "symbol":"CRWD", "source_type":"analyst_curated"}
→ {"ok": true, "action": "removed", "source_type": "analyst_curated"}

Postgres: CRWD | analyst_curated | status: removed (history preserved)
JSON: unchanged
```

## 4. Provenance

| Field | User entry | Analyst-curated entry |
|-------|-----------|----------------------|
| `source_type` | `user` | `analyst_curated` |
| `added_by` | `user` | `analyst curated` |
| `data.analyst_source` | — | e.g., "Goldman Sachs" |
| `data.curation_note` | — | optional freeform |
| In `watchlist.json`? | YES | NO |
| In Postgres? | YES | YES |

## 5. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| Analyst-curated entries supported in API | **PASS** |
| Analyst-curated entries supported in UI | **PASS** (gold badge, source dropdown) |
| User-watchlist behavior preserved | **PASS** (JSON unchanged, blue badge) |
| Provenance stored correctly | **PASS** (`source_type`, `added_by`, `data.analyst_source`) |
| Implementation stayed manual support only | **PASS** (no automation) |
