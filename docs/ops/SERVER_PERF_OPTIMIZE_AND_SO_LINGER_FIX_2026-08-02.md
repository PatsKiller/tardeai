# Server Performance Optimization & SO_LINGER Fix — 2026-08-02

## Summary

Multi-pronged server optimization to eliminate "server busy · 26 feeds" states, stale
data, and connection exhaustion. Culminated in a critical fix: `SO_LINGER=0` was
truncating large HTTP responses (the 4 MB React JS bundle), causing blank pages.

## Changes

### 1. DB Connection Pool (`scripts/db_adapter.py`)

Replaced thread-local `psycopg2` connections with `psycopg2.pool.ThreadedConnectionPool`
(min 3, max 20 connections). Each borrowed connection gets safety net timeouts
(`idle_in_transaction_session_timeout`, `lock_timeout`, `statement_timeout`).
`close_thread_conn()` returns connections to the pool instead of closing them.

- **Before**: Every request thread opened its own connection, held it for its lifetime
- **After**: Shared pool, connections reused, idle-in-transaction kills prevented

### 2. Overview Cache (`scripts/api_v2.py`)

Single-flight, thread-safe in-memory cache for `/api/v2/overview` (30s TTL).
`_overview_compute()` does the heavy aggregation; `overview()` returns cached result
or acquires a lock to compute. Contending requests get the slightly-stale cache.

### 3. ETag / No Cache-Bust (`apps/command-center-v3/src/hooks/useApi.ts`)

Removed unconditional `?_=Date.now()` cache-busting. Server sends ETag /
`Cache-Control: no-cache`, browser sends `If-None-Match`, server returns 304.
Reduces response body transfer for idle polling by ~90%.

### 4. Concurrency Tuning (`scripts/portfolio_server.py`)

- `DASHBOARD_MAX_CONCURRENCY`: 48 → 32
- `_WATCHDOG_ABANDON_SEC`: 25s → 12s
- Semaphore with 5s timeout; excess requests get 503 "server_busy" + Retry-After
- Health + static assets bypass the semaphore so the reconnect banner always clears

### 5. Cron Freshness Watcher (`scripts/cron_freshness_watcher.py`)

New cron-scheduled agent that monitors data source freshness (finnhub, yahoo_finance,
finviz, watch_decision, entry_planner, schwab_sync, indicator_cache) and
auto-retries stale jobs via shell commands. Logs events to `system_health_events` table.

### 6. Socket Options Bug: SO_LINGER=0 (CRITICAL FIX)

**What went wrong**: An earlier optimization added `SO_LINGER=0` on the server's listen
socket to prevent CLOSE-WAIT buildup from dead Tailscale peers. This setting is
**inherited** by every accepted client socket.

**Mechanism**: `SO_LINGER` with `l_onoff=1, l_linger=0` tells the kernel to RST the
connection immediately on close, discarding any unsent data in the send buffer. For the
4 MB React JS bundle (`index-_Th8NYNL.js`), the kernel socket buffer held only ~1-2 MB.
`wfile.write()` would block after filling the buffer, and when the server's
`Connection: close` took effect, the remaining 2-3 MB were silently dropped.

**Symptoms**:
- Blank white page in all browsers (Chrome, Edge, Firefox)
- Each curl request for the JS bundle returned a different (incorrect) byte count
- `Content-Length: 4079436` header was correct, but actual bytes delivered varied
  between 1.9 MB and 3.1 MB
- No console errors — React simply never mounted because the JS was broken

**Fix**:
1. Removed the `_LingerHTTPServer` class and `SO_LINGER` socket option entirely
2. Added `wfile.flush()` after every `wfile.write()` in all response paths to ensure
   Python-level buffers drain before the connection closes
3. CLOSE-WAIT is now handled by `request.settimeout(30)`, bounded concurrency (32),
   and `finish()` returning DB connections

**Detection heuristic for future**:
```bash
# File on disk
SIZE=$(stat -c%s dist/assets/index-*.js)
# Download 3 times — all must match
for i in 1 2 3; do
  DL=$(curl -s --max-time 30 http://127.0.0.1:7777/v3/assets/index-*.js | wc -c)
  echo "Attempt $i: $DL bytes (expected $SIZE)"
done
```
If any download size differs from the file size (and from other downloads), a
truncation bug exists.

## Also Added

### HealthHub Enhancements (`apps/command-center-v3/src/pages/HealthHub.tsx`)

- **Agent Coverage** section: cards with freshness-colored borders showing each agent's
  last run and status
- **Score Breakdown**: weighted category contributions from `decomposition` data
- **Auto-Fix Statistics**: fix rates and top issues from `/api/v2/health/autofix-ledger`
- **Pending Escalations**: badge count + compact list from `/api/v2/health/escalations`
- **History tab**: anomaly highlighting for significant score swings

### SystemHub Consolidation (`apps/command-center-v3/src/pages/SystemHub.tsx`)

- Consolidated 17 tabs into 6 monitoring + 3 admin tabs
- Removed duplicate data domains per Ops Page Constitution Rule 4
- Added `Health →` link to canonical HealthHub page

### Health Agent Score Decomposition (`scripts/health_agent.py`)

`compute()` now returns a `decomposition` dict with weighted category scores, effective
weights, finding counts, and top penalty per category. Each finding includes `impact_score`.

## New Backend Endpoints

| Endpoint | Source | Description |
|---|---|---|
| `GET /api/v2/health/coverage` | `health_agent_snapshots` | Agent coverage & freshness |
| `GET /api/v2/health/autofix-ledger` | `claude_interventions`, `coder_dispatch_audit` | Auto-fix statistics |
| `GET /api/v2/health/escalations` | `claude_escalation_queue.json`, `pipeline_health_approvals` | Pending escalations |

## Rollback Notes

If the site goes blank again:
1. Check JS bundle download integrity (see detection heuristic above)
2. Verify no `SO_LINGER` on the server socket: `grep -r SO_LINGER scripts/portfolio_server.py`
3. Restart the server: `systemctl --user restart portfolio-server` (or kill + re-nohup)

## Weekend-Aware Pipeline Status (2026-08-02)

### Problem
The Overview API (`/api/v2/overview`) reported `pipeline_status: "fresh"` based on a timestamp
written by the orchestrator when it last ran successfully. There was no staleness computation —
the orchestrator just hardcoded `"status": "fresh"` in `_freshness.json`. This meant:
- Pipeline "fresh" status never decayed, even on weekends
- No off-market awareness — a Friday run still showed "fresh" on Sunday
- No visible "last refreshed" timestamp in the HomeHub UI

### Fix

**Backend (`scripts/api_v2.py`):**

1. **Smart pipeline_status computation** in `_overview_compute()`:
   - Computes `pipeline_age_hours` from `completed_at` in `_freshness.json`
   - Computes `market_status` from day-of-week and rough ET hour (weekend/regular/afterhours/closed)
   - Threshold: 26h baseline, +24h per Sat/Sun in the gap
   - Status values: `"fresh"`, `"weekend"`, `"afterhours"`, `"stale"`
   - New fields in overview response: `pipeline_age_hours`, `market_status`, `refreshed_at`
   - On weekdays: stale after 26h without a run
   - On weekends: stale only when the gap exceeds 26h + (2×24h) = 74h

2. **Force-refresh endpoint** (`GET /api/v2/overview/refresh`):
   - Bypasses the 30s cache, computes fresh, stores back
   - Safe for off-market use — no side effects, just re-reads data files

**Frontend (`apps/command-center-v3/src/pages/HomeHub.tsx`):**

3. **Enhanced "Data:" tile** in the HomeHub sidebar:
   - Shows pipeline status with contextual color: fresh=normal, weekend=amber, stale=red
   - Shows age: `"39h ago · market weekend"`
   - Shows last refreshed time: `"refreshed 10:54 PM"`
   - **Off-market refresh button** appears when market is weekend/closed or data >12h old
   - Button calls `refetchOverview()` which triggers a fresh `/api/v2/overview` fetch
