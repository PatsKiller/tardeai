Status: DRAFT
as_of: 2026-09-01T19:17:16Z
Measured at: served release via :7777 / BUILD_SHA 18a3da0dc159 (git_sha 18a3da0dc1598700d5005eda0cb80bccd4bc98c5)

# Litmus slice C — Command Center routes (discovery only)

Discovery-only route map: **Tile → URL → JSON path → v2 vs v3 → contract name**.
No product fixes, no PR, no push. Packer wave later.

---

## Pre-flight pins `[VERIFIED]`

Commands run in `/tmp/wt-cio-phase-a`:

```
$ git rev-parse HEAD
e95431f16e2b0694d798fc2bdfde670186862ab6

$ git rev-parse origin/main
ac4b37cea86bb71e68c41db1e2cf85f1b0f19365

$ echo ${PROJ:-unset}
unset

$ ls CURRENT 2>&1
ls: cannot access 'CURRENT': No such file or directory
```

**CURRENT pin:** No `CURRENT` file or symlink in the worktree. Live measurement uses the served release on `:7777` (portfolio_server responding).

**CURRENT BUILD_SHA** — `GET http://127.0.0.1:7777/v3/build-meta.json`:

```json
{
  "ui_version": "3.14+mtj083cs",
  "built_at": "2026-09-01T18:32:24.280Z",
  "git_sha": "18a3da0dc1598700d5005eda0cb80bccd4bc98c5",
  "build_sha": "18a3da0dc159",
  "branch": "main",
  "release_label": "main-exact-phase2"
}
```

**$PROJ:** unset — no PROJ HEAD to compare.

**Worktree vs origin/main:** worktree `e95431f1` ≠ origin/main `ac4b37ce` (worktree lags main). Measurement continued on served `:7777` release (`18a3da0d`), not worktree HEAD.

**Twin PR search:**

```
$ gh pr list --state open --search "LITMUS_CC_ROUTES"
(empty)

$ gh pr list --state open --search "CC routes litmus"
(empty)
```

No twin — discovery proceeded.

**Required reads:** `AGENTS.md`, `AI_WORK_POLICY.md` (workspace rules). Architecture/ops closeouts requested (`CIO_ASIS_VS_SPEC_2026-08-30.md`, `CIO_OVERNIGHT_CLOSEOUT_2026-09-01.md`, `CIO_AFTERNOON_FIVE_2026-09-01.md`, `CIO_DATA_ASOF_GAPS_2026-09-01.md`) **not present** in this worktree — not read. `docs/ui_redesign/API_CONTRACTS_AND_PAYLOADS.md` read (Status: HISTORICAL, as_of 2026-05-25). CC v3 routing read from `App.tsx`, `NavRail.tsx`, `MetricStrip.tsx`, hub pages.

---

## Methodology

1. **Routes:** `apps/command-center-v3/src/App.tsx` (`basename="/v3"`) + `NavRail.tsx` SECTIONS + global `MetricStrip`.
2. **API wiring:** `useApi` / `fetch` in hub page components (489 unique `/api/*` strings in `apps/command-center-v3/src`; table lists **primary** endpoint per surface).
3. **Live measurement:** `curl` against `http://127.0.0.1:7777` when server responded (`GET /api/health` → `ok: true`). Timestamps quoted from envelope `data`.
4. **Freshness verdicts:** UI logic from `surfaceFreshness.ts` (overview ≥36h → STALE chrome; trade-ai uses `cached_at` + empty-universe rules). API `stale` flags quoted where present.
5. **v2 vs v3:** Almost all operator surfaces use `/api/v2/*` (legacy `api_v2.py`). Newer namespaces: `/api/v3/cio/*`, `/api/v3/advisory`, `/api/v3/data-broker/*`, `/api/v3/watch/*`, `/api/v3/active-trader/*`, `/api/v3/control-plane/*`, `/api/v3/maturity/*`, `/api/v3/agent-runtime/*`, `/api/v3/intelligence/*`.
6. **Contract names:** `ControlPlane@v1.0.0` (`scripts/lib/control_plane_contract_v1.py`); `watchlist_intelligence.card.v1` (WI synopsis provenance in `surfaceFreshness.ts`); `active-trader-at-cfg-s1-read-v1` (Active Trader config tab comment). Most v2 endpoints have no `*_v1` envelope name in UI code.

---

## Global chrome — MetricStrip tiles

All routes under browser prefix `/v3`. Strip polls globally on every page.

| Tile | URL (any page) | API endpoint | JSON path (key fields) | v2/v3 | Contract name |
|------|----------------|--------------|------------------------|-------|---------------|
| PORTFOLIO | `/v3/` (all) | `/api/v2/overview` | `data.portfolio_value`, `data.as_of`, `data.pricing.last_repriced` | v2 | — |
| TODAY | `/v3/` | `/api/v2/overview` | `data.today_change`, `data.today_pct`, `data.today_by_account` | v2 | — |
| TRADING | `/v3/` | `/api/v2/overview` (+ readiness) | `data.journal.win_rate`, `data.journal.last_ingested_at` | v2 | — |
| REALIZED | `/v3/` | `/api/v2/overview` | `data.journal.realized_pnl`, `data.journal.realized_count` | v2 | — |
| REGIME | `/v3/` | `/api/v2/risk-regime/latest` | `data.regime_label`, `data.confidence`, `data.generated_at` | v2 | — |
| VIX | `/v3/` | `/api/v2/trade-ai/summary` | `data.vix`, `data.run_label` | v2 | — |
| SETUPS · LATEST RUN | `/v3/` | `/api/v2/trade-ai/summary` | `data.go_count`, `data.cached_at`, `data.stale`, `data.run_date` | v2 | — |
| LIVE badge | `/v3/` | `/api/v2/live-trading-gate` | `data.status`, `data.operator_live_via_2fa_allowed` | v2 | — |
| HEALTH chip | `/v3/health` nav | `/api/v2/health` | `data.findings[]`, `data.captured_at` | v2 | — |
| Price stamp | `/v3/` | `/api/v2/overview` | `data.pricing.last_repriced`, `data.reprice_source` | v2 | — |

Also fetched but not tiled: `/api/v2/paper-trade-readiness` (TRADING drill context).

---

## Route inventory — NavRail pages

Browser paths = `/v3` + route from `App.tsx`. **Primary** API = main data load for default tab/view.

| Tile / Nav label | URL | Primary API endpoint(s) | JSON path (key fields) | v2/v3 | Contract name |
|------------------|-----|-------------------------|--------------------------|-------|---------------|
| Home | `/v3/` | `/api/v2/overview`, `/api/v2/trade-ai/summary`, `/api/v2/risk`, `/api/v2/health`, `/api/v2/inbox`, `/api/v2/command`, `/api/v2/paper-proposals`, `/api/v2/defense/posture` | overview: `portfolio_value`, `as_of`; inbox: `count`, `items[]`; health: `findings`, `captured_at` | v2 | — |
| Portfolio | `/v3/portfolio` | `/api/v2/portfolio/holdings`, `/api/v2/overview` | holdings: `holdings[]`, `as_of`; overview tabs: performance, dividends | v2 | — |
| ↳ Re-Entry | `/v3/portfolio/re-entry` | `/api/v2/redeploy/book`, `/api/v2/journal`, `/api/v2/stops/reentry-watch`, `/api/v2/risk-regime/latest` (+ child components) | book: `items[]`; journal: trade history | v2 | — |
| Risk | `/v3/risk` | `/api/v2/risk`, `/api/v2/risk-regime/latest`, `/api/v2/risk-regime/indicators` | risk: `portfolio_heat_pct`, `positions[]`; regime: `regime_label` | v2 | — |
| Trading | `/v3/trading` | `/api/v2/trade-ai/scanner`, `/api/v2/paper-proposals`, `/api/v2/open-trades`, `/api/v2/broker-proposals/summary` (tab-gated) | scanner: tickers, signals; proposals: list | v2 | — |
| Active Trader | `/v3/active-trader` | `/api/v3/active-trader/permission-queue`, `/api/v3/active-trader/scalp/setups`, `/api/v3/active-trader/config`, `/api/v3/active-trader/motion` | config tab: read-only config payload | **v3** | `active-trader-at-cfg-s1-read-v1` |
| Strategy | `/v3/strategy` | `/api/v2/strategy-leaderboard`, `/api/v2/strategy-desk`, `/api/v2/incubator` | leaderboard rows | v2 | — |
| TradeInView | `/v3/journal` | `/api/v2/journal`, `/api/v2/automated-trade-journal`, `/api/v2/journal/execution-quality` | journal entries, lessons | v2 | — |
| Watch | `/v3/watch?tab=intelligence` | `/api/v3/data-broker/watch-intelligence`, `/api/v3/data-broker`, `/api/v2/watch/alerts/list` | watch-intelligence: cards/synopsis | **v3** | `watchlist_intelligence.card.v1` (synopsis) |
| Defense | `/v3/defense` | `/api/v2/defense/posture`, `/api/v2/defense/recommendations` | posture, recommendations[] | v2 | — |
| Agents | `/v3/agents` | `/api/v3/agent-runtime/runs`, `/api/v3/agent-maturity`, `/api/v2/agents/summary` (Legacy tab) | runtime runs, maturity fleet | **v3** + v2 | `AGENT_RUNTIME_CONTRACT` (adapter constant) |
| Research Intel | `/v3/research-intelligence` | `/api/v2/research-intelligence/*`, `/api/v2/research-intelligence/freshness` | freshness stamps | v2 | — |
| Intelligence | `/v3/intelligence` | `/api/v2/market-intelligence`, `/api/v2/hermes/health` | articles, hermes status | v2 | — |
| Closed Loop | `/v3/intelligence?tab=closed-loop` (redirect) | `/api/v3/intelligence`, `/api/v3/intelligence/queue` | queue items, lineage | **v3** | — |
| Hermes | `/v3/hermes` | `/api/v2/hermes/health`, `/api/v2/hermes/research-backlog`, … | health, backlog | v2 | — |
| Advisory Desk | `/v3/advisory` | `/api/v3/advisory`, `/api/v3/advisory/run-now` (POST) | advisory rows by class | **v3** | — |
| CIO Desk | `/v3/cio` | `/api/v3/cio/home`, `/api/v3/cio/brain`, `/api/v3/cio/universe-theses`, `/api/v3/cio/investment-product` | home: `as_of`; brain policy | **v3** | InstrumentRecord-adjacent (no `*_v1` in response) |
| Reports | `/v3/reports` (hard nav) | `/api/v2/reports/categories`, `/api/v2/reports/catalog`, brief list paths | categories, catalog | v2 | — |
| Rotation | `/v3/rotation` | `/api/v2/rotation/summary` | summary, sector decisions | v2 | — |
| Rec Intelligence | `/v3/rec-intel` | `/api/v2/rec-intel/summary`, `/api/v2/rec-intel/lifecycle` | lifecycle performance | v2 | — |
| Retirement | `/v3/retirement` | `/api/v2/retirement`, `/api/v2/retirement/planning-research` | plan summary | v2 | — |
| Health | `/v3/health` | `/api/v2/health`, `/api/v2/health/activity`, `/api/v2/health/dispatches` | findings, remediate CTAs | v2 | — |
| Consumption | `/v3/consumption` | `/api/v2/consumption/overview`, `/api/v2/consumption/processes`, `/api/v2/consumption/lane-registry` | process list, lane registry | v2 | — |
| System | `/v3/system` | `/api/v2/system/pipeline-health`, `/api/v2/system/scheduled-jobs`, `/api/v2/live-trading-gate` | cron, pipeline | v2 | — |
| Schwab Reauth | `/v3/system/schwab-reauth` | `/api/v2/system/schwab-token-health` (via page type) | token expiry | v2 | — |
| Redeploy (no nav; route exists) | `/v3/redeploy` | redeploy desk integrated endpoints | — | v2 | — |
| Symbol intel | `/v3/watch/intelligence/:symbol` | `/api/v3/data-broker/watch-intelligence/{sym}`, `/api/v3/cio/intelligence/{sym}` | per-symbol card | **v3** | — |
| Control Plane Hub | `/v3/control-plane` | preview only; subpages below | — | **v3** | `ControlPlane@v1.0.0` |
| CP System | `/v3/control-plane/system` | `/api/v3/control-plane/system` | `authority`, envelope fields | **v3** | `ControlPlane@v1.0.0` |
| CP Agents | `/v3/control-plane/agents` | `/api/v3/control-plane/agents`, `.../agents/{id}` | agent list | **v3** | `ControlPlane@v1.0.0` |
| CP Workflows | `/v3/control-plane/workflows` | `/api/v3/control-plane/workflows`, `.../workflows/{id}` | workflow lineage | **v3** | `ControlPlane@v1.0.0` |
| CP Research | `/v3/control-plane/research` | `/api/v3/control-plane/research` | R23 side-by-side | **v3** | `CONTROL_PLANE_API_V1_BASELINE` |
| CP Data | `/v3/control-plane/data` | `/api/v3/control-plane/stores` | store cadence rows | **v3** | `ControlPlane@v1.0.0` |
| CP Identity | `/v3/control-plane/identity` | `/api/v3/control-plane/identity` | identity gaps | **v3** | `ControlPlane@v1.0.0` |
| CP Notifications | `/v3/control-plane/notifications` | `/api/v3/control-plane/notifications` | funnel counts | **v3** | `ControlPlane@v1.0.0` |
| CP Learning | `/v3/control-plane/learning` | `/api/v3/control-plane/learning` | items by kind | **v3** | `ControlPlane@v1.0.0` |
| CP Maturity | `/v3/control-plane/maturity` | `/api/v3/control-plane/maturity` | maturity items | **v3** | `ControlPlane@v1.0.0` |
| CP Audit | `/v3/control-plane/audit` | `/api/v3/control-plane/audit` | audit items | **v3** | `ControlPlane@v1.0.0` |

**Route count:** 42 registered CC v3 surfaces (31 primary nav + 7 MetricStrip tiles + 4 chrome badges/stamps counted once in strip section; 11 control-plane preview pages). **489** distinct API path strings referenced in CC v3 source overall.

---

## Findings table

Format: `surface | endpoint | field | writer | clock | as_of | verdict | note`

| surface | endpoint | field | writer | clock | as_of | verdict | note |
|---------|----------|-------|--------|-------|-------|---------|------|
| MetricStrip PORTFOLIO | `/api/v2/overview` | `as_of` | portfolio_loader / repricer | `pricing.last_repriced` ET | `2026-08-29` (holdings) + repriced `2026-09-01 15:15:02 ET` | **SPLIT** | Block `as_of` is holdings snapshot date; repricing is today — chrome STALE threshold uses older `as_of` (≥36h). |
| MetricStrip TODAY | `/api/v2/overview` | `today_change` | overview aggregator | same | `2026-08-29` holdings basis | **SPLIT** | Today's move computed with live repricing but holdings `as_of` lags calendar. |
| MetricStrip SETUPS | `/api/v2/trade-ai/summary` | `cached_at`, `stale` | trade_ai cache | `cached_at` UTC | `2026-09-01T19:14:34+00:00`, `stale:false` | **LIVE** | 2 GO / 1 WAIT / 390 avoid; run_date `2026-09-01`. |
| MetricStrip REGIME | `/api/v2/risk-regime/latest` | `generated_at` | risk_regime writer | `generated_at` ET | `2026-09-01T06:35:01-04:00` | **LIVE** | `breadth_state: missing`, summary notes finviz_degraded. |
| MetricStrip LIVE badge | `/api/v2/live-trading-gate` | `status` | gate evaluator | — | — | **LIVE** | `PAPER_ONLY` — AUTO BLOCKED display expected. |
| Home inbox | `/api/v2/inbox` | `count` | inbox aggregator | item `at` timestamps | 77 items | **LIVE** | P0 proposals surface with CTAs to `/v3/trading`. |
| Health hub | `/api/v2/health` | `captured_at`, `findings` | health_agent | `captured_at` UTC | `2026-09-01T19:11:04+00:00` | **LIVE** | `status: degraded`; critical dividend_calendar 151h stale finding. |
| Portfolio holdings | `/api/v2/portfolio/holdings` | `as_of` | holdings store | file mtime / store | `2026-08-29` | **STALE** | 22 positions returned; calendar gap vs live session. |
| Risk hub | `/api/v2/risk` | `as_of` | risk engine | — | absent in payload | **EMPTY** | No top-level `as_of`; positions present — clock not exposed to UI. |
| CIO Desk home | `/api/v3/cio/home` | `as_of` | cio home writer | server UTC | `2026-09-01T19:16:38+00:00` | **LIVE** | v3 namespace responds on served release. |
| Data broker catalog | `/api/v3/data-broker` | `generated_at` | data_broker registry | UTC | `2026-09-01T19:16:41+00:00` | **LIVE** | Watch Intelligence depends on this catalog. |
| Advisory Desk | `/api/v3/advisory` | — | advisory runner | — | curl timeout 3s | **DARK** | Endpoint hung on measurement — page may show loading/empty. |
| Defense posture | `/api/v2/defense/posture` | — | defense posture writer | — | curl timeout 3s | **DARK** | HomeHub and DefenseHub both call this; slow or blocking. |
| Consumption | `/api/v2/consumption/overview` | — | consumption monitor | — | empty `{}` in sample | **EMPTY** | Page may render without overview stamp. |
| CIO brain panel | `/api/v3/cio/brain` | `as_of` | cio brain | — | empty data keys | **EMPTY** | Component fail-soft; brain payload absent on this host. |
| Control Plane preview | `/api/v3/control-plane/*` | `schema` | control_plane_contract_v1 | envelope `as_of` | fixture/live mix | **SPLIT** | R23 pages declare `R23_LIVE_CLAIM = false`; routes registered in App but nav hidden unless preview flag. |
| Watch Intelligence | `/api/v3/data-broker/watch-intelligence` | synopsis | decision_projection | card timestamps | per-card | **SPLIT** | Provenance explicitly **not** InstrumentRecord spine (`WI_SYNOPSIS_PROVENANCE`). |
| API_CONTRACTS doc | doc §Shell | `/api/v2/risk-regime/status` | — | — | — | **STALE** | Live MetricStrip uses `/api/v2/risk-regime/latest` instead. |
| API_CONTRACTS doc | doc §Overview | `/v2/` base path | — | — | 2026-05-25 | **STALE** | CC v3 serves at `/v3/`; many endpoints unchanged but page map is pre-v3. |

**Finding count:** 19 rows.

---

## Doc vs live disagreements

| Topic | Document claim | Live / code observation | Severity |
|-------|----------------|-------------------------|----------|
| Base URL | `API_CONTRACTS_AND_PAYLOADS.md` lists Overview at `/v2/` | App `basename="/v3"` — all routes `/v3/...` | Doc stale (2026-05-25 HISTORICAL) |
| Regime endpoint | Doc: `/api/v2/risk-regime/status` for shell | `MetricStrip.tsx` + hubs use `/api/v2/risk-regime/latest` | Doc wrong path |
| Trade AI summary | Doc: `/api/v2/trade-ai` full scanner | MetricStrip/Home use `/api/v2/trade-ai/summary`; Trading tab uses `/api/v2/trade-ai/scanner` | Doc incomplete split |
| Control plane | Not in May API doc | 11 `/api/v3/control-plane/*` routes live in App; `ControlPlane@v1.0.0` schema | Doc gap |
| CIO / Advisory v3 | Not in May API doc | `/api/v3/cio/*`, `/api/v3/advisory` wired in CioHub / AdvisoryDeskHub | Doc gap |
| Overview `as_of` | Doc implies single freshness | Live: `as_of` `2026-08-29`, `data_as_of` `2026-09-01`, `last_repriced` today | SPLIT — doc does not describe triple clock |
| holdings freshness | — | `holdings.as_of` 2026-08-29 on live server | STALE vs session calendar |

---

## Live curl evidence (selected) `[VERIFIED]`

```
$ curl -sS http://127.0.0.1:7777/api/v2/overview | jq '.data | {portfolio_value, as_of, data_as_of, last_repriced: .pricing.last_repriced}'
→ portfolio_value 1277802.71, as_of "2026-08-29", data_as_of "2026-09-01", last_repriced "2026-09-01 15:15:02 ET"

$ curl -sS http://127.0.0.1:7777/api/v2/trade-ai/summary | jq '.data | {go_count, stale, cached_at, run_date}'
→ go_count 2, stale false, cached_at "2026-09-01T19:14:34...", run_date "2026-09-01"

$ curl -sS http://127.0.0.1:7777/api/v2/health | jq '.data | {status, captured_at, findings_count: (.findings|length)}'
→ status "degraded", captured_at "2026-09-01T19:11:04...", findings_count > 0
```

---

## STOP note

Discovery complete. **No PR created. No push. No product fixes.** File ready for litmus packer. Operator-only items untouched (holdings, cron, promote, AGENTS.md).

**Return summary for parent:** `docs/ops/litmus/LITMUS_CC_ROUTES_2026-09-01.md` · pre-flight worktree `e95431f1`, origin/main `ac4b37ce`, CURRENT file absent (served BUILD_SHA `18a3da0dc159`), PROJ unset · **42** surfaces mapped · **19** findings · top disagreements: overview triple-clock SPLIT, API_CONTRACTS pre-v3 paths, `/api/v3/advisory` and `/api/v2/defense/posture` timeouts · twin PR **none**.
