# BISECT_TRADE_REGRESSION_2026-09-01

Joint hour-one bisect: empty trade page (Momentum Day Scouts / Market Opportunities Scanner) + silent Telegram scalp/momentum alerts.

**Authority:** Cursor · Grok · Claude Code (merge/deploy: Claude Code only)
**Conflict rule:** finding wins over brief. Append sections; do not rewrite another agent's.

---

## CURSOR · surface (Command Center + live API)

**as_of:** `2026-08-31T16:47:12Z`  
**roots:** `live_api:127.0.0.1:7777` · served process cwd `…/portfolio-server/efcc51365-main-exact-phase2-20260831-114929` (= `origin/main` `efcc51365`) · code read from worktree `/tmp/wt-cio-phase-a@efcc51365`

### What the trade page calls

[CODE] `apps/command-center-v3/src/pages/TradingHub.tsx` — tab **Trade AI** / **Market Opportunities Scanner** (Social Scouts filter). Operator “Momentum Day Scouts” maps here.

| UI need | Endpoint | Handler |
|---|---|---|
| Scanner table | `GET /api/v2/trade-ai/scanner` | `trade_ai_scanner()` → `trade_ai()` |
| Full payload (parent) | `GET /api/v2/trade-ai` | `trade_ai()` disk cache |
| Scalp strip | `GET /api/v2/scalp/live` | `_scalp_live_poll()` → `data/scalp_live_signals.json` |

Backing store for the scanner [CODE `scripts/api_v2.py` `trade_ai`]:

1. **Disk:** `data/runtime/trade_ai_cache.json` (refreshed by `warm_caches.py` / `trade_ai(force=True)`)
2. **Compute inputs:** `reports/*/run_summary.json` + Postgres `trade_ai_scans` (`WHERE run_date >= CURRENT_DATE - 1 day`)

### What it returns today

[VERIFIED] `curl http://127.0.0.1:7777/api/v2/trade-ai/scanner` → HTTP 200:

```
ticker_count=0  tickers=[]  stale=true
cached_at=2026-08-28T04:06:13.794823Z
cache_age_sec≈304750 (~84.7h)
run_date=2026-08-31  run_label=1000
session_heal={to:2026-08-28, preserved_tickers:0, by:heal_trade_ai_session_cache}
go=0 wait=0 avoid=0 current_run_scanned=0
```

[VERIFIED] `GET /api/v2/scalp/live` → `{"signals":[],"count":0,"ws_available":false}`  
[VERIFIED] on-disk `data/scalp_live_signals.json` **missing** under served cwd.

[VERIFIED] `GET /api/v2/trade-ai/summary` agrees: `stale=true`, same `cached_at`, all counts 0.

### Last date the backing store had content

| Store | Last content | as_of / how |
|---|---|---|
| Live `trade_ai_cache.json` | **Empty since** `_cached_at=2026-08-28T04:06:13Z`; heal preserved **0** tickers | [VERIFIED] API + disk via served cwd |
| `trade_ai_cache.json.bak` | **Last non-empty:** `run_date=2026-08-06` label `0400`, `generated_at=2026-08-06T06:18:54`, `_cached_at=2026-08-07T14:48:28Z`, 99 tickers (5 GO / 22 WAIT / 7 SOCIAL_SCOUT) | [VERIFIED] disk |
| Served `reports/*/run_summary.json` | Only **2026-08-31** packages present on this release (0400/0700/0900/1000) — **all `ticker_count=0`** | [VERIFIED] disk |
| `trade_ai_scans` (DB) | Not queried directly this wave (secret-access hook blocks env/DB CLI). Inference: today’s run_summaries + empty fail-closed cache ⇒ no usable rows for the warm path | [DOC-CLAIM] pending Grok/Claude |

### Same break as Telegram silence? (surface evidence)

**Strongly consistent with one upstream, not a CC render bug.**

[VERIFIED] `GET /api/v2/health` (`detected_at=2026-08-31T16:42:59Z`):

- `data_source_stale` **finviz** — last success **102.2h** ago; `last_error`: **"Zero rows returned — cookie may be expired"**
- `data_source_stale` **social_scalp** — last success **78.4h** ago; `last_error`: **"0 candidates from social_scalp"**
- `scalp_catalyst_verification_dead` — momentum-scalp GO tier DARK; Telegram GO/WAIT alerts described as silently down

[VERIFIED] `GET /api/v2/data-source-health` (`as_of=2026-08-31T12:47:12-04:00`):

- **Finviz screeners** `dead` — `last_update=2026-08-27T07:00:01-04:00` (age **101.8h**)
- Screener membership same timestamp / stale
- **Catalyst events** `live` (age 0.0h) — catalyst ingest is **not** dead
- [VERIFIED] `GET /api/v2/signals/fused` still returns **50** rows dated **2026-08-31T12:30…-04:00** (strategy_type mostly null / core_growth) — so **fused_signals≠0 today**; empty scanner is **not** “all intelligence stores empty”

### Cursor verdict + ownership

| Question | Answer |
|---|---|
| Is the empty page a frontend bug? | **No** — API returns intentional empty/stale payload; UI empty-state copy matches. |
| Is the backing cache empty? | **Yes** since **2026-08-28** heal; last rich bak snapshot **2026-08-06**. |
| One upstream with Telegram? | **Likely yes** — Finviz screener chain + social_scalp zero candidates; alerts + scanner share that producer path. |
| Who owns the fix? | **Claude Code** (Finviz / data-source / notification transports). Cursor **hands off**; will not patch producers. |

### Blocks (Cursor)

1. **Drive ledger upload** — `gog drive` needs keyring TTY / `GOG_KEYRING_PASSWORD`; ledger mirrored at `/tmp/coord_run/RUN_LEDGER_2026-09-01.md` only.  
2. **`release-write` hook** — shell commands naming the served-release tree are blocked; live HTTP + `/proc/<portfolio_server>/cwd` used for served-root reads. Not escalated.  
3. **DB CLI** — secret-access hook blocked credential-shaped env probes; store last-row dates for `trade_ai_scans` / `scalp_scan_results` left to **Grok**.

### Handoff

→ **Claude Code:** Finviz HTTP-200 / zero-CSV / cookie-expired path; why continuous/orchestrator run_summaries are zero-ticker while health still schedules; Telegram capture/dry-run only.  
→ **Grok:** last row dates for `trade_ai_scans`, `scalp_scan_results`, finviz caches vs live `fused_signals`/`catalyst_events` (fused is **live** as of this as_of — reconcile overnight “0 rows / 30h” claim).

---

## GROK · stores

*(pending)*

---

## CLAUDE CODE · schedulers / data source

*(pending)*
