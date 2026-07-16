# RI v3.1 Phase 0 Diagnosis — 2026-07-16

All verified live (DB user `trade_ai`, port 7777, feed route `/api/v2/research-intelligence`).

| # | Item | Expected (prompt) | Actual (live) | Adapt / Flag |
|---|------|-------------------|---------------|--------------|
| 0.1 | Feed latency | slow request-time compute | **Cold 0.80s, warm 14ms** (60s single-flight cache works). Payload is the problem: **1.92 MB** per response, re-serialized (`_json_clean` deep walk) + re-gzipped every poll because the client cache-busts (`_=`ts, `cache: no-store`) | **FLAG-BACK: server-busy root cause is NOT feed computation.** It is single-process saturation: heavy JSON endpoints × several open tabs × zero HTTP caching |
| 0.2 | Server topology | flask/gunicorn? | `portfolio_server.py` — stdlib `ThreadingHTTPServer`, ONE Python process (GIL), 58 threads, **88–140% CPU at ~1 req/s**. `BoundedSemaphore(DASHBOARD_MAX_CONCURRENCY=32)`, 3s acquire timeout → 503 `server_busy`. Health/static exempt | adapt; topology change out of scope (flagged, separate decision) |
| 0.3 | "11 feeds" pollers | enumerate | ~25 distinct `useApi` endpoints across pages; globals: overview/trade-ai/risk 60s, schwab accounts-live **35s**, health 120s. Page-load fires 10–15 hooks at once per tab → semaphore burst → 503 banner ("11 feeds" = simultaneous failing hooks) | A4 poll budget |
| 0.4 | Retry behavior | hammer? | Not a pure hammer: 503 → linear backoff `retryAfter*retries` cap 12s, max 10 retries; non-503 has separate retry. But every fetch is cache-busted (`_=${Date.now()}` + `no-store`) — **ETag/304 impossible without client change**; red banner shows whenever ≥1 hook is failing even with good data on screen | A3 rework |
| 0.5 | feedback schema | hide column? | `research_intelligence_feedback`: item_id/starred/vote/note/categories/symbol/meta_json/timestamps. **No `hidden` column** → migration per B2 (documented, not overloading vote) | migrate |
| 0.6 | starred_only | exposed? | Confirmed: build_feed param + route flag both live | B1 is UI only |
| 0.7 | sources | URL availability | `source_urls_json` jsonb **array** on 10,318 rows; `_sources_from_row` already parses | E1 feasible |
| 0.8 | Beauty Farm exemplar | find entry path | Rows 9821/9822, `research_type='topic_research'`, industry-screener digests ("Medical Instruments & Supplies… Beauty Farm Medical & H…", "as of mid-2026" phrasing) — screener-noise regurgitated into advisory prose; exactly the WS-D class | D2/D1 target |
| 0.9 | VIX '—' | dead read? | Header reads `/api/v2/trade-ai .vix` ← disk cache ← run_summary.json, which carries **`vix: 0`** (orchestrator's VIX fetch dead). Live VIX EXISTS: `market_regime_indicators.indicator_key='vix_close'` = **15.94 @ 06:30 today** | F2: fall back to vix_close in trade-ai cache compute |
| 0.9b | Setups tile | 0/0/0 at 11:40 | At diagnosis time latest run 0900 shows **2 GO / 0 WAIT / 54 NOGO** — tile zeros in the 11:42 snapshots were a stale/torn cache read, not "no runs" (crons run 09/10/12/14/16/17:30/19). Honest empty state still worth adding pre-09:00 | F3 |
| 0.10 | External lanes stalled | cron? auth? credits? | Cron ALIVE (`hermes_top20_external_intel` every 2h) but every run: `called: 0, deferred: 2222`. Chain: (a) "top-20" query returns **1,145 rows** (the `in_directive_watch=true` OR-clause adds every directive symbol); (b) governor defers T2 correctly, ALLOWs ~21 T0/T1 — but (c) **`hermes_external_researcher.py` CRASHES on every call: `PROMPT.format()` KeyError `'"recommendation"'`** — the appended `build_external_research_json_schema()` block contains unescaped `{}` braces. Broken since the CIO-parity/Maturity-5 prompt change ~07-01/02. NOT auth, NOT credits | F1: fix format-field bug (`.replace()` substitution); NOT a governor change |

## Root-cause statement (WS-A flag-back honored)
The "Reconnecting… server busy" storms are **not** feed compute. Profile: one GIL-bound Python process; per-request costs dominated by JSON serialization + gzip of MB-scale payloads; clients cache-bust every request so nothing is ever 304'd; page loads burst 10–15 concurrent hooks per tab into a 32-slot/3s semaphore; several tabs were open during the 11:42 snapshots. The snapshot+ETag architecture is still the right fix (removes serialize+gzip from the hot path and enables 304s) **provided the client stops cache-busting snapshot endpoints** — that client change is part of A2/A3.

## Poll budget (A4, before → after)
| Endpoint | Before | After |
|---|---|---|
| /api/v2/research-intelligence (+freshness, staged) | 90s / 120s / 60s, cache-busted | 300s with ETag/If-None-Match (snapshot changes a few times/day) |
| /api/v2/schwab/accounts-live | 35s | 120s (broker cache updates slower than 35s) |
| /api/v2/overview, /trade-ai, /risk | 60s | 120s (all served from disk caches refreshed by warm crons ≤8 min) |
| /api/v2/hermes/discovery-inbox (RI rail) | 300s | 600s |
| others ≥120s | unchanged | unchanged |

## Other flag-backs
- `hidden` migration added to `research_intelligence_feedback` (B2) — documented here.
- E3 prefs: CC v3 already uses localStorage (`useTerminalUi` hook exists) → density toggle rides the existing pattern, no new store.
