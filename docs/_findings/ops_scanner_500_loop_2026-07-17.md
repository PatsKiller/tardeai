# Ops: Market Opportunities Scanner 500-loop + Postgres slot exhaustion — 2026-07-17

## Symptom (operator-visible)
Command Center showed "showing last-good data · live refresh paused (server busy · 16 feeds)"
and the Trading → Trade AI scanner tile sat on
"⚠ Scanner data temporarily unavailable — /api/v2/trade-ai did not respond … HTTP 500"
from roughly 07:50 until the 08:09:25 service restart.

## Root-cause chain (verified, in order)
1. **Cold boot 06:32** — the box rebooted; portfolio-server came up with cold caches and
   immediately pinned ~1 core (GIL saturation: 30+ concurrent request threads at 2–6% each,
   not one hot loop; process consumed 1h37m CPU over 1h37m wall for its entire first life).
2. **Full-payload polling** — the scanner tile (plus Home, Reports, Central Intelligence)
   polled the FULL `/api/v2/trade-ai` payload every 60s from every open client.
   The payload is ~1.7 MB, and **95% of it is plain-AVOID universe rows the UI never
   renders** (1,154 of 1,198 rows on the day; the default "Actionable" view shows 43).
3. **Serialize-per-poll under saturation** — each poll re-`json.dumps`ed + re-gzipped the
   multi-MB body on a GIL-saturated process, pushing responses past the ~30s client abort;
   the compute watchdog then reaped the abandoned computes (`reaped abandoned compute:
   /api/v2/trade-ai after ~30s`) → HTTP 500 → the tile retried every 60s → kill-loop.
   `BrokenPipeError` tracebacks in the log are clients hanging up — symptom, not cause.
4. **Postgres slot exhaustion (the second-order failure)** — during the storm the server
   leaked idle DB connections at ~2–3/min (backend_start drip 08:11→08:26 after the
   restart, until **97 of ~100 slots** were held by the server pid and
   `FATAL: remaining connection slots are reserved for … SUPERUSER` began). Connections
   outlived their request threads; plain-`idle` sessions have no timeout (only
   idle-in-transaction=120s is set), so they never reaped.
5. **Silent cache poisoning** — with slots exhausted, `warm_caches.py` (separate process)
   could not connect; `_db_query` returned None and it **wrote an empty trade_ai cache
   (3 KB, 0 tickers)** at 12:27Z. Every downstream consumer then showed a legitimate-looking
   zero-row scan. This matches the standing rule: DB-fed writers must fail closed, not
   write empties.

The 08:09:25 restart (clean systemd stop/start) cleared the thread backlog and deployed the
then-uncommitted ETag/body-cache/semaphore-exemption hardening; reaps and 500s stopped
immediately. The connection drip continued until slots filled at ~08:26.

## Fixes applied 2026-07-17 (this session)
- **`/api/v2/trade-ai/scanner`** (api_v2.py): slim projection — full rows only for
  actionable (GO/WAIT/MANUAL_REVIEW) and pill-flagged rows; plain-AVOID universe rows trim
  to the 13 fields the UI actually reads (copy lists, counts, CI sweep). 350 KB raw vs
  1,656 KB (‑79%); ~68 KB gzipped on the wire. Memoized per underlying cache generation;
  own weak ETag (`W/"scan-…"`) so the 304/body-cache path works (verified: 304 in 14 ms).
- **Consumers repointed**: TradingHub scanner + CentralIntelligencePages → `/scanner`;
  HomeHub + ReportsHub → the existing ~500 B `/summary`. No UI surface fetches the full
  payload on a poll loop anymore (it remains available for drill/debug).
- **Semaphore exemption** extended to `/trade-ai/summary` + `/trade-ai/scanner`.
- **Pre-warm cron** (`*/5 * * * *`): curls `/api/v2/trade-ai` + `/scanner` with
  `Accept-Encoding: gzip` so the serialized/gzip body cache is hot within 5 min of ANY
  server restart — a restart can never cold-serve the scanner into the watchdog again.
  (Compute-side warm was already in place: warm_caches.py every 8 min.)
- Cleared the slot exhaustion (service restart → 97 slots freed), re-ran warm_caches
  (cache back to 1.7 MB / 1,198 tickers), Playwright-verified the Trading hub fetches only
  `/summary` + `/scanner`, renders rows, no error banner.

## Prevention status
- **Scanner 500 kill-loop: prevented** — the polled payload is ~25× smaller, 304s after
  first fetch, semaphore-exempt, and pre-warmed after restarts. Reproducing the dashboard
  load post-fix showed zero watchdog reaps and zero 500s.
- **Connection leak: mitigated, not root-caused.** Under post-fix load the drip does NOT
  reproduce (server holds 0–1 idle conns vs 2–3/min before), consistent with the leak being
  driven by the reap/abort storm itself — but the exact leak path (which thread type
  strands its conn on abort) was not pinned down. **Follow-ups — ALL CLOSED same day:**
  1. ✅ Health-agent slot checks (`collect_db_connection_health`): `db_slots_single_app_high`
     warning when one application_name holds >40 conns, `db_slots_near_exhaustion` critical
     at >70 total, and `db_slots_exhausted` critical when the probe connect itself dies
     FATAL (direct psycopg2 connect so the FATAL is catchable). Thresholds in
     `config/health_agent_policy.json` → `db_connections.slots_*`. Alert-only (no
     auto-remediation — restart target needs the attribution the finding provides).
  2. ✅ `ALTER ROLE trade_ai SET idle_session_timeout = '30min'` applied + verified
     (`rolconfig` confirms). Prerequisite shipped first: `db_adapter._get_conn` pings a
     conn idle >60s (only when transaction-idle, never disturbing an open txn) and
     transparently rebuilds a server-side-killed conn — verified E2E with
     `pg_terminate_backend` (caller saw no error, new backend pid). Runbook updated.
  3. ✅ Fail-closed guard in `api_v2.trade_ai(force=True)`: a 0-ticker compute NEVER
     overwrites a non-empty cache — last-good is served flagged
     `cache_error=empty_compute_kept_last_good`, and the refusal is logged.

## Gotchas recorded
- `/api/v2/health` is currently reporting overall 48 (execution_health 0,
  risk_protection 5) — pre-existing, unrelated to this incident, needs its own look.
- `psql` as trade_ai works via ~/.pgpass (Reports Desk v1 finding); when slots are
  exhausted even psql fails — free a slot before diagnosing, or the box looks DB-dead.
