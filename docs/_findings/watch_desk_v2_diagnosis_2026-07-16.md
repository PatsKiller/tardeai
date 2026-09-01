# Watch Desk v2 Phase 0 Diagnosis — 2026-07-16

Status:      HISTORICAL
as_of:       2026-07-16T14:22:41-04:00
Measured at: efcc51365 / not measured

(DB user is `trade_ai`, not `johnclaw`; port 7777. Routes: /api/v2/watchlist/items, /screener-finds/candidates, /watchpool, /sectors/monitor, /pullback-macd/candidates.)

| # | Item | Actual (live) | Decision |
|---|------|---------------|----------|
| 0.1 | **$98,650 header flip** | Delta NAMED: **SPAXX, the Fidelity money-market sweep = $96,911** (drift = intraday move). Mechanism found at `overview()` api_v2.py:1903-1907: if `derived_total` (Σ holdings market_value) differs from `portfolio_totals.total_value` by >$500, overview **silently swaps** to derived. When SPAXX is momentarily unpriced mid-pipeline (14:00 = last_pipeline_run exactly), derived drops ~$96.9K → header flips unlabeled. Both sources agree ($1,268,501) outside pipeline windows. Cash rows (4) sum to exactly `total_mv_excluded` ($187,767) — "excluded" = cash excluded from cost-basis math, intentional | A1: kill the silent override; canonical = portfolio_totals.total_value; drift becomes a flag, not a swap |
| 0.2 | Directive regrowth | 387 active (317 trend + 58 ticker + 12 sector), 179 archived, 27 paused. History: 378→386 active in 4 days (+2-3/day). Dedup dry-run: 31 archivable (29 dead 0-hit challengers, 2 family-merge into #244). **No dedup/pause_cold cron exists** — service/monitor/discovery/keyword crons only | B: fence missing AND hygiene unscheduled (both, per decision gate) |
| 0.3 | Creation paths | 8 inserters. `canonical_family()` consulted ONLY in hermes_think_tank.py. NOT consulted: claude_challenger_curator (the Tier-3 dup source), strategy_planner, sector_research_universe, telegram_command_handler, api_v2 rotation seeder. `_watch_directive_create` dedups ticker-kind exact-symbol only | B1: shared gate helper wired into non-think-tank creators |
| 0.4 | Advisory bands | `watchlist_items.setup_advisory` is FREE TEXT ("RSI 46 · band 40-55"), written by setup_quality_prior.py/pipeline; 424 rows "awaiting enrichment"; no favorable/advisory/caution enum exists in the data. The UI facets count keyword matches that the writer almost never emits → **the 0/1/1 facet is vocabulary mismatch, not a stale engine** | A2: honesty fix — facet counts computed server-side over the same 200-row corpus; empty facets grayed with tooltip naming the writer |
| 0.5 | Ranking | `ORDER BY wi.hermes_rank ASC NULLS LAST` (api_v2:6162/6178), LIMIT 200 of **5,167** active/researched | C3: "Top 200 of 5,167 by Hermes rank" |
| 0.6 | Pullback screener | ZERO holdings/held/dismiss references in 741 lines; no dismissal table | C1 badge + D2 dismissal memory needed |
| 0.7 | Sector monitor | `_sectors_monitor` in api_v2 (no standalone script); XLRE/Financials fixes live there | A4 |
| 0.8 | ChatGPT quota badge | Badge = `chatgpt_curated_top20/20` from curation status; the consumer is the **2-hourly `hermes_top20_external_intel` cron** (5 */2), NOT page views — increments during RTH are the cron firing (lanes restored today, so it consumes again) | label the badge with source; no bug |
| 0.9 | Payloads | watchlist/items **1.41 MB / 1.1s**; watch-directives **793 KB**; watchpool 70 KB; sectors 22 KB; pullback 18 KB; screener-finds 6 KB | E: watchlist/items + watch-directives get the trim/ETag treatment |
| 0.10 | ToS imports | `tos_watchlists` table + import allowlist exist in api_v2; `imports/tos_watchlists/` directory absent (never used) | report-only: create dir on first import; no build |

## Decision gate
- WS-A1 P0 confirmed (mechanism, not mystery).
- WS-B: BOTH problems — creation fence absent outside think_tank AND zero scheduled hygiene. Regrowth ≈ +2-3/day from challenger/think-tank cycles; 31 immediately archivable.
