# Phase P5-2 / P5-3 Investigation — Database Maintenance and Monitoring

**Date:** 2026-04-20
**Investigator:** Claude Opus 4.6
**Status:** Read-only investigation complete

---

## Pre-flight Results

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Autovacuum enabled | on | `on` | **OK** |
| Global vacuum_scale_factor | 0.2 (default) | `0.2` | **OK** — no per-table overrides set |
| Global analyze_scale_factor | 0.1 (default) | `0.1` | **OK** |
| Tables with dead tuples | Varies | portfolio_snapshots: 22 dead, performance_daily: 11 dead, run_summary: 4 dead | **OK** — normal, autovacuum will clean |
| Existing /api/health | Basic | Returns `{ok, version, port, holdings_exists}` — no DB stats | **OK** |
| Existing /api/db/health | None | Does not exist | **OK** — needs to be created |
| db_status() helper | Exists | Line 433 in db_adapter.py — returns connection string or fallback text | **OK** |
| pg_stat_user_tables accessible | Yes | `trade_ai` role has SELECT on pg_stat_user_tables | **OK** |

**Pre-flight: ALL PASS. Safe to proceed.**

---

## Section A: Current Autovacuum Situation

### Global settings (PostgreSQL defaults)
- `autovacuum = on`
- `autovacuum_vacuum_scale_factor = 0.2` (vacuum after 20% of table is dead tuples)
- `autovacuum_analyze_scale_factor = 0.1` (analyze after 10% changes)

### Per-table settings
**NONE.** No tables have custom `reloptions` set (all show NULL).

### Autovacuum activity observed
| Table | live_rows | dead_rows | last_autovacuum | last_autoanalyze |
|-------|-----------|-----------|-----------------|------------------|
| price_cache | 130,984 | 0 | 2026-04-20 07:25 | 2026-04-20 07:25 |
| trade_ai_state | 57 | 0 | 2026-04-20 10:21 | 2026-04-20 10:21 |
| personal_history | 24 | 0 | never | 2026-04-19 21:01 |
| portfolio_snapshots | 2 | 22 | never | never |
| run_summary | 2 | 4 | never | never |
| holdings | 1 | 4 | never | never |
| performance_daily | 1 | 11 | never | never |

### Assessment
- **price_cache:** Healthy — autovacuum/autoanalyze running. 130K rows with 0 dead tuples.
- **trade_ai_state:** Healthy — autovacuum running (frequent DELETE+INSERT pattern handled).
- **Small tables (2-24 rows):** Autovacuum hasn't fired because the default threshold is `50 + 0.2 * n_live_tup` — with only 1-24 live rows, you need ~50 dead tuples before vacuum triggers. The 22 dead tuples in portfolio_snapshots will be vacuumed once they cross 50.
- **No immediate concern.** With current data volumes, the PostgreSQL defaults are adequate.

### P5-2 Recommendation
The tier_2 doc recommends `scale_factor = 0.1` for high-write tables. With current volumes:
- `price_cache` (131K rows): default works fine. Vacuum triggers at ~26K dead rows.
- `trade_ai_state` (57 rows): already auto-vacuumed. DELETE+INSERT every 10-15 min creates dead tuples, but count is tiny.
- `personal_history` (24 rows): rarely written. No benefit from tuning.

**Recommendation: Apply the tier_2 suggested tuning as a small safety net (it won't hurt and prevents issues if volumes grow), but it's NOT urgent.**

---

## Section B: Current Monitoring/Health State

### Existing endpoints
- `GET /api/health` — returns `{ok, version, port, holdings_exists}`. No DB info.
- `GET /api/freshness` — returns pipeline freshness manifest. No DB stats.

### Existing helpers
- `db_adapter.db_status()` — returns connection string or "JSON fallback" text. Used by: nothing currently (available but uncalled by any endpoint).
- `db_adapter._execute()` — can run arbitrary SQL if USE_DB is True.

### Existing alerting paths (for future wiring)
- `telegram_alert.send_telegram(message)` — used by multiple scripts. Works, tested today.
- `portfolio_alerts._send_telegram(message, project_root)` — same but with project_root context.
- No existing DB-specific alerting.

---

## Section C: Implementation Approach

### P5-2 (Autovacuum tuning) — 3 SQL statements, no code

```sql
ALTER TABLE price_cache SET (autovacuum_vacuum_scale_factor = 0.1);
ALTER TABLE trade_ai_state SET (autovacuum_vacuum_scale_factor = 0.1, autovacuum_analyze_scale_factor = 0.05);
ALTER TABLE performance_daily SET (autovacuum_vacuum_scale_factor = 0.1);
```

That's it. No script changes. Can verify immediately with:
```sql
SELECT relname, reloptions FROM pg_class WHERE relname IN ('price_cache', 'trade_ai_state', 'performance_daily');
```

### P5-3 (Health endpoint) — ~30 lines in portfolio_server.py

Add `GET /api/db/health` that returns:
```json
{
  "ok": true,
  "status": "PostgreSQL @ localhost:5432/trade_ai",
  "tables": [
    {"name": "price_cache", "live_rows": 130984, "dead_rows": 0, "size": "38 MB", "last_autovacuum": "..."},
    ...
  ],
  "checked_at": "2026-04-20T..."
}
```

Uses `db_adapter._execute()` to query `pg_stat_user_tables` + `pg_total_relation_size`. Falls back to `{ok: false}` if connection fails.

---

## Architect Questions Answered

### 1. What is the current autovacuum / analyze situation?
**Working correctly with PostgreSQL defaults.** Autovacuum is enabled, firing on the high-write tables (price_cache, trade_ai_state). Small tables haven't triggered yet because they're below the 50-tuple threshold. No custom per-table settings configured.

### 2. Are there already any DB health endpoints, monitoring scripts, or alerts?
**NO DB-specific monitoring.** Only `/api/health` (no DB info) and `/api/freshness` (pipeline, not DB). `db_adapter.db_status()` exists as a helper but isn't exposed via any endpoint.

### 3. What existing server/API location is best for /api/db/health?
**`scripts/portfolio_server.py`** in the `do_GET` handler, right after the existing `/api/freshness` endpoint (which follows the same pattern: read system state, return JSON). Pattern is already established.

### 4. What exact metrics are realistically available with low implementation risk?
- Per-table: `n_live_tup`, `n_dead_tup`, `n_tup_ins/upd/del`, `last_autovacuum`, `last_autoanalyze`
- Per-table size: `pg_total_relation_size()`
- Connection status: `_get_conn()` success/failure
- `db_status()` text

All accessible via single SQL query against `pg_stat_user_tables`.

### 5. Which metrics are most useful right now?
- **Connection alive** (ok/not ok) — catches Postgres being down
- **Per-table live_rows** — catches if a table unexpectedly empties
- **Per-table dead_rows** — catches vacuum not running
- **Per-table size** — catches unexpected growth
- **last_autovacuum** — catches if maintenance stopped

### 6. Is there a Telegram/alerting path we could reuse later?
**YES.** `telegram_alert.send_telegram(message)` works and is used by multiple scripts. Wiring a "DB unhealthy" Telegram alert is trivial future work (not in this pass).

### 7. Should P5-2 and P5-3 be implemented together or split?
**Together.** P5-2 is 3 SQL statements (< 1 minute). P5-3 is ~30 lines of code. Total effort ~30 minutes. No benefit from splitting.

### 8. Biggest risks of doing too much vs minimal first pass?
- **Too much:** Adding alerting, dashboards, automated remediation — over-engineering for 7 tables with <200K total rows
- **Minimal first pass:** Tuning applied, endpoint available. Monitor manually via `curl /api/db/health` or browser. Add Telegram alerts later if needed.

---

## Recommended Minimal Scope

### P5-2: Autovacuum tuning
- 3 ALTER TABLE statements for high-write tables
- Verify via `pg_class.reloptions`
- No code changes, no script changes

### P5-3: Health endpoint
- Add `GET /api/db/health` to `portfolio_server.py`
- Query `pg_stat_user_tables` + sizes
- Return JSON with per-table stats
- Return 503 if DB connection fails
- ~30 lines total

### Does NOT require sudo/root
- `ALTER TABLE ... SET (...)` works as the `trade_ai` table owner (verified: trade_ai owns all tables)
- Health endpoint is in user-space server
- Completely user-level implementation

---

## Risks

| Risk | Severity | Notes |
|------|----------|-------|
| ALTER TABLE on live system | VERY LOW | Only changes table metadata (reloptions), no data impact, no locks |
| Health endpoint exposes row counts | LOW | Only accessible on localhost:7777, no sensitive data |
| Dead tuples in small tables | LOW | Will auto-clean once threshold is reached. Tuning makes this faster. |
