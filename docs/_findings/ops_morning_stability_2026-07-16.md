# Findings — Morning Ops Stability (2026-07-16)

**Date:** 2026-07-16 (ET morning session)  
**Scope:** Command Center v3 desk reliability, Research Intelligence, Finviz screener, Telegram scalp delivery, Health Agent interpretation  
**Status:** Fixes shipped on `main` (see commits below). Desk **reads** stay 24/7; RI **writes** overnight / after close only.

---

## 1. Executive summary

| Area | Symptom | Root cause | Fix |
|------|---------|------------|-----|
| Dashboard | “Reconnecting…”, timeouts, empty setups | Multi‑MB API payloads + unbounded request queue / concurrent RI rebuilds | Gzip, semaphore timeout + 503, health bypass, RI single-flight cache |
| `/api/v2/trade-ai` | 30s timeout → 0 GO/WAIT | Cold path recomputed ~250s when disk cache mid-write; saturated slots | Never recompute on GET; atomic cache write |
| `server_busy` JSON | `{"ok":false,"error":"server_busy"}` | All concurrency slots held; health waited on same semaphore | Health/static bypass semaphore; single-flight RI; cheaper gzip |
| Finviz pipeline_critical | Transaction aborted 07:00 / 08:00 | Membership lock timeout without ROLLBACK poisoned txn | SAVEPOINT per screener + nested membership + recovery |
| Telegram scalps silent | NEW GO not delivered | Critic DOWNGRADE/BLOCK forced P2 | Deliver NEW GO with critic line still in message |
| Health Agent “didn’t fix” | 56/100, only paper-stuck auto-fixed | Auto-remediation allowlist excludes pipeline DB bugs / log noise / SIEM / stops | Documented — by design; code fix for Finviz done separately |
| Iris stale 7d | AGENT STALENESS alert | Weekly SLA hit max age; jobs queued | Not a total agent outage |
| RI during RTH | Heavy LLM/ingest competed with trading | Hourly synth + mid-day topic ingest | Overnight gate + cron |

---

## 2. Dashboard / portfolio_server reliability

### 2.1 Failure mode

1. `GET /api/v2/research-intelligence?limit=100` ≈ **3.3 MB** JSON; `GET /api/v2/trade-ai` ≈ **1.7 MB**.
2. MetricStrip + hubs poll many large endpoints every 60–90s over Tailscale.
3. `DASHBOARD_MAX_CONCURRENCY` (was 24) threads each held for multi-second build + gzip + slow client write.
4. New requests (including `/api/health`) waited forever → CLOSE-WAIT pileup (100–300+) → whole desk “dead.”

### 2.2 Secondary failure (`trade_ai`)

`trade_ai()` was designed to serve `data/runtime/trade_ai_cache.json` (warmed by `warm_caches.py`, ~250–300s).  
If a request **read mid-write**, JSON parse failed → fallthrough to `_compute_trade_ai()` **on the request path** → multi-minute hold of a request slot → cascade.

### 2.3 Fixes shipped

| Change | Location |
|--------|----------|
| Gzip large JSON (`compresslevel=1`, threshold 4KB) | `scripts/portfolio_server.py` `json_response` |
| Semaphore acquire timeout → **503** `server_busy` (not infinite wait) | `ReusableHTTPServer.process_request_thread` |
| **Health + static `/v3/` bypass** concurrency semaphore | `_sem_exempt_path` + `MSG_PEEK` path |
| Request socket timeout (default 30s) | `process_request_thread` |
| `trade_ai` never recomputes on GET if any cache/memory exists; atomic rename write | `scripts/api_v2.py` `trade_ai` / `_write_trade_ai_cache` |
| RI feed 45–60s TTL cache + **single-flight lock** | `scripts/api_v2.py` `_research_intelligence_feed` |
| RI list cap 50 | Hub + API `lim` max |
| useApi: cache-bust, `refreshing` state, **soft-retry 503** | `apps/command-center-v3/src/hooks/useApi.ts` |
| Refresh desk toast + multi-endpoint refetch | `ResearchIntelligenceHub.tsx` |

### 2.4 Operator notes

- Hard-refresh browser after deploys (Tailscale: `https://ms01-openclaw.tail163d14.ts.net/v3/`).
- Occasional 503 under burst is **expected** and should recover in seconds; health should still return 200.
- If desk fully dead: restart `scripts/portfolio_server.py` (watchdog may also adopt).

---

## 3. Research Intelligence — overnight / non-trading only

### 3.1 Policy

| Session (ET) | RI **content production** | RI **desk read** |
|--------------|---------------------------|------------------|
| Premarket 04:00–09:30 | **Blocked** | Live |
| RTH 09:30–16:00 | **Blocked** | Live |
| Afterhours / closed / weekend / holiday | **Allowed** | Live |

Python helper: `market_session.is_research_intelligence_window()`.

### 3.2 Scripts

| Script | Role |
|--------|------|
| `scripts/non_trading_hours_gate.sh` | Skip job if session is `regular` or `premarket` |
| `scripts/run_research_intelligence_overnight.sh` | Archive → topic bridge → synth → narrative → ingest |
| `scripts/install_research_intelligence_overnight_cron.sh` | Idempotent crontab block |

### 3.3 Cron (installed on host)

```
30 20 * * 1-5   full overnight batch (after close)
15  2 * * *     deep overnight full batch
15  5 * * *     archive-only
20  * * * *     hourly topic synth (gated — no-op mid-session)
45 20 * * 1-5   topic_ingestion after close
45  2 * * *     topic_ingestion overnight
50 21 * * *     reground
```

Removed unguarded mid-day: topic_ingestion 09:00/13:00, reground 14:50, unguarded hourly synth.

### 3.4 Docs

- Architecture: `docs/architecture/RESEARCH_INTELLIGENCE_V2.md` §9  
- UI copy: desk notes “Content production runs overnight / after close only”

---

## 4. Finviz screener `pipeline_critical`

### 4.1 Root cause

1. `bond_etf_income` membership update → **lock timeout**.
2. Exception logged but **no ROLLBACK** → connection left in `InFailedSqlTransaction`.
3. Later `INSERT INTO ticker_strategy_classifications` failed for all subsequent screeners.
4. Pipeline registry marked run failed → Telegram `pipeline_critical` at 07:00 and 08:00.

### 4.2 Fix

`scripts/finviz_screener_runner.py`:

- `_ensure_txn_usable()` — recover aborted transaction  
- Per-screener `SAVEPOINT`  
- Nested savepoint for membership only  
- Stamp `last_run` even when zero new tickers  
- Summary counts `membership_failures` / `db_write_failures`

One lock timeout no longer fails the entire multi-screener run.

---

## 5. Telegram scalps — silent NEW GO

### 5.1 Root cause

`continuous_runner` fired `NEW_GO` (e.g. JTAI score 44) but `telegram_alert_router.classify_alert` returned **P2_DASHBOARD_ONLY** when Critic was **DOWNGRADE** or **BLOCK**, so messages never left the host.

### 5.2 Fix

`scripts/telegram_alert_router.py` + `config/operator_alert_policy.yaml`:

- NEW GO still **P0** with critic text in message  
- Knobs: `scalp_send_on_critic_downgrade`, `scalp_send_on_critic_block`, `scalp_score_jump_telegram`  
- Continuous runner restarted to load module

---

## 6. Health Agent interpretation (not a “did nothing” bug)

Alert excerpt (08:30 ET):

- Health **UNHEALTHY 56/100** — dominated by **execution_health=0**, **risk_protection=5**  
- pipeline_freshness can still be **100** while Finviz pipeline_critical alerts fire separately  
- Auto-fixed only allowlisted types (e.g. `approved_paper_test_stuck` via `cleanup_stale_proposals.py`)

**Not auto-remediated (by design):**

- Finviz DB transaction bugs → code fix (done)  
- log_errors / SIEM P0–P1 → code/operator  
- Orphaned stops / unprotected positions → risk ops  
- Iris 7d stale → weekly SLA; system health **queued** 2 iris jobs at 09:00  

See also: `docs/HEALTH_AGENT.md`.

---

## 7. Research Intelligence ticker card polish (same day)

Earlier in session (prior commits on branch history):

- Company name, sector/industry, what-they-do, news/sentiment, analyst consensus on cards  
- Professional muted palette (no “Christmas tree”)  
- Security layer: `identity`, `news_snapshot`, `analyst_snapshot` in `research_intelligence_security.py`

---

## 8. Commit map (this morning’s stability work)

| Commit | Summary |
|--------|---------|
| `44002ece` | NEW GO Telegram despite Critic DOWNGRADE/BLOCK |
| `86bad56f` | Refresh desk feedback + cache-bust |
| `910131be` | Finviz SAVEPOINT / txn isolation |
| `9a002946` | trade_ai never recompute on request path |
| `8a38f9dc` | Gzip JSON, busy 503, RI TTL cache |
| `04d8880d` | RI overnight / non-trading only |
| `40455c85` | Health bypass, RI single-flight, 503 soft-retry |

*(Later same-day RI v3 workstreams may appear above these on `main`.)*

---

## 9. Verification checklist

```bash
# Health must stay up under load
curl -sS -m 5 http://127.0.0.1:7777/api/health

# Large feeds should be fast when warm + gzip
curl -sS -m 15 -H 'Accept-Encoding: gzip' -o /dev/null -w '%{http_code} %{time_total} %{size_download}\n' \
  http://127.0.0.1:7777/api/v2/trade-ai
curl -sS -m 20 -H 'Accept-Encoding: gzip' -o /dev/null -w '%{http_code} %{time_total} %{size_download}\n' \
  'http://127.0.0.1:7777/api/v2/research-intelligence?limit=50'

# RI gate (should skip during RTH/premarket)
bash scripts/non_trading_hours_gate.sh echo should_not_print_mid_session

# Overnight block present
crontab -l | sed -n '/BEGIN research-intelligence-overnight/,/END research-intelligence-overnight/p'
```

---

## 10. Follow-ups (not done this session)

1. Slim RI list payload (list DTO vs full card) so even cold builds stay &lt;500KB.  
2. Pre-gzip or strip trade_ai tickers for MetricStrip (counts-only endpoint).  
3. Health auto-remediate: optional safe “retry finviz screener once” (policy decision).  
4. Confirm iris queued jobs complete and clear 7d staleness.  
5. CACI NEARTRIGGER / orphaned stops — risk desk, not RI.

---

*Documented 2026-07-16 for operator handoff and A1A index sync.*
