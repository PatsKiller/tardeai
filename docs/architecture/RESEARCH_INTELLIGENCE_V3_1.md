# Research Intelligence v3.1 — Institutional Desk (Reliability · Provenance · Curation)

Status:      ACTIVE
as_of:       2026-07-16T12:57:17-04:00
Measured at: efcc51365 / not measured

**Shipped:** 2026-07-16 (commits 775d94f4, 13ec3953, 1ea3fc0e, c70a5fc0, b2aaf1f2) · Feed `version: "3.1"`
**Diagnosis:** `docs/_findings/ri_v3_1_diagnosis_2026-07-16.md` — read it; the server-busy flag-back is canonical.

## WS-A — Reliability (P0)
Root cause was NOT feed compute (cold 0.8s / warm 14ms): one GIL-bound ThreadingHTTPServer re-serializing + gzipping MB-scale JSON per cache-busted poll across tabs, bursting a 32-slot/3s semaphore. Fix:
- `research_intelligence_materialize.py` → per-lane snapshots in `data/runtime/ri_snapshots/` (gitignored); triggers: queue drains, 06:35 cron, `POST /research-intelligence/rebuild` (flocked, RTH-allowed compute).
- Feed GET serves snapshots for default views: **warm 10–19 ms; If-None-Match → 304 in 1.1 ms / 0 bytes** (was 1.97 MB/poll). `json_response` handles `__etag__` generically (304 BEFORE dumps/gzip). `meta.served_from: snapshot|live` + `generated_at` on every response.
- Calm client: If-None-Match in `useApi`, 304 = fresh-not-stale, exponential backoff w/ jitter (1→30s), red banner → quiet amber chip over intact data; hub gets "Desk built HH:MM ET" + "Rebuild desk (~30s)".
- Poll budget: RI 300s, discovery 600s, overview/trade-ai 120s, accounts-live 35→120s (full table in findings).
- **OPEN (flagged, operator decision):** CLOSE-WAIT zombie threads (~33 within 10 min) exhaust request slots regardless of cap — handler compute is unbounded after client disconnect. Needs gunicorn/uvicorn or a compute watchdog. `DASHBOARD_MAX_CONCURRENCY=64` set in .env as relief (server now loads .env). Old-bundle tabs amplify until reloaded.

## WS-B — Curation
★ Saved tab (starred_only), "saved Nd ago"; `hidden` column migration on `research_intelligence_feedback` — quiet ✕, default-excluded at build_feed, "N hidden · show" fold with Unhide (never deletes); ▼ demotes rank (mirror of star, no auto-suppression); `feedback_tallies_7d` per category in freshness report; staged rows show created/expires (amber ≤3d).

## WS-C — Provenance
Desk banner (built/next-build), absolute-ET hover on freshness dots, wire lines through `fmtET()` (date shown >24h), single ET formatter. **C4 partial:** per-figure quote as-of inside narrative needs source-row quote timestamps — enforced negatively by the WS-D undated-claim lint; positive stamps are follow-up.

## WS-D — QA lint (zero LLM)
`research_intelligence_qa_lint.py`, runs inside materialization: `undated_claim`, `off_universe_mention` (tickerish tokens in implications + corporate-suffix name detector — the "Beauty Farm Medical" class), `unsourced_advisory`, `no_counter_view` (assembles a counter_view from Hermes divergence when possible; else "single-view — treat as unconfirmed" tag), `duplicate_of` (0.8 shingle overlap). Flags cap Tier A→B, render as gray chips, tally in `freshness_report.qa_flag_counts`. First run: 50 briefs → 21 flagged (11 unsourced / 8 off-universe / 4 undated).

## WS-E — Links + polish
Domain-labeled source links (max 4 + overflow, noopener); shared `TickerLinks` (Finviz/Yahoo/EDGAR/TradingView/Watchlist, one config map); tabular numerals desk-wide. Density = existing Terminal UI prefs (no new store). E4 keyboard nav skipped per its own timebox rule.

## WS-F — Ops restore
- External lanes: root cause was `PROMPT.format()` KeyError on the appended JSON schema's braces — every call crashed pre-API since ~07-02 (NOT auth/credits; governor untouched). Fixed via `.replace()`. Restored live: chatgpt row 26781 + grok 26785 `status=sent`. Absolute staleness checks added to `intel_table_staleness_monitor.py` (lanes 96h, vix_close 30h).
- VIX: run_summary carries `vix=0` (orchestrator fetch dead) → trade-ai cache falls back to `market_regime_indicators.vix_close` (15.94 verified in API).
- Setups tile: "— before first run" honest empty state (snapshot zeros were a stale cache read; real runs exist).
