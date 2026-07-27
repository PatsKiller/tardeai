# Active Trader Stage 0 — Route, API, and DB Map

**Run ID:** 20260722-01 · **Base SHA:** 87c2fa09fa95a8a69233959b04b1144e1297b923 · **Date:** 2026-07-22
All facts below are evidence-backed from the worktree at the base SHA unless marked UNVERIFIED.

---

# PART 1 — /v3 FRONTEND (apps/command-center-v3)

## 1.1 Stack

Source: `apps/command-center-v3/package.json`

- react `^18.3.1`, react-dom `^18.3.1`, react-router-dom `^6.23.1`
- lightweight-charts `^4.2.3`, recharts `^2.15.3`, reactflow `^11.11.4`
- Dev: @playwright/test `^1.61.1`, typescript `^5.5.4`, vite `^5.4.2`, @vitejs/plugin-react `^4.3.1`
- Scripts: `build` = design-token guard → chip-scope test → `tsc` → `vite build`; `test:e2e` = `playwright test`
- Entry: `index.html` → `/v3/cc-boot.js` (server-injected) + `/src/main.tsx`
- Vite: `base: '/v3/'`, outDir `dist`, dev proxy `/api` → `http://127.0.0.1:7777`; `build-meta` plugin stamps `dist/build-meta.json` with `ui_version` `3.12+<base36>` per build
- tsconfig: strict, ES2020, `jsx: react-jsx`, `noEmit`

## 1.2 Routes

`src/App.tsx` — `<BrowserRouter basename="/v3">` (App.tsx:194); route table in `Shell()` at App.tsx:149-181:

| Path | Element |
|---|---|
| `/` (index) | HomeHub |
| `portfolio` | PortfolioHub |
| `risk` | RiskHub |
| `trading` | TradingHub |
| `go/order/:intentId` | redirect → `trading?tab=Broker Orders&intent=` |
| `go/proposal/:proposalId` | redirect → `trading?tab=Proposals` |
| `manual-execution` | Navigate → `/trading?tab=Entry+Desk` |
| `strategy` | StrategyHub |
| `agents` | AgentsHub |
| `intelligence` | IntelligenceHub |
| `research-intelligence` | ResearchIntelligenceHub (`research` redirects here) |
| `hermes` | HermesHub |
| `retirement` | RetirementHub |
| `journal` | JournalHub (`trade-in-view` redirects here) |
| `watch` | WatchHub (`watchlist`/`watchpool`/`sectors`/`pullback-macd` redirect in) |
| `defense` | DefenseHub |
| `reports` | ReportsHub |
| `rotation` | RotationIntelligence (`advisor-changes` redirects in) |
| `redeploy` | RedeployDesk |
| `rec-intel` | RecommendationIntelligence |
| `health` | HealthHub |
| `consumption` | ConsumptionHub |
| `system` | SystemHub |

Trading-hub tabs are query-state, not routes (`src/pages/TradingHub.tsx:30`):
`'Trade AI', 'Options', 'Open Trades', 'Proposals', 'Entry Desk', 'Execution', 'Broker Recon', 'Scalp', 'ATM Controls', 'Broker Orders', 'Schwab Accounts'` (aliases at TradingHub.tsx:31-40). Journal is a top-level route, not a Trading tab.

## 1.3 Trading surfaces and their APIs

- **Trading hub** (`TradingHub.tsx:84-97`): `/api/v2/trade-ai/scanner`, `/api/v2/warrior-audit/latest`, `/api/v2/open-trades`, `/api/v2/paper-proposals`, `/api/v2/execution-quality`, `/api/v2/scalp/live`, `/api/v2/hermes/subject-intel-map?type=scalp`, `/api/v2/atm/setup-advisory`, `/api/v2/broker-reconciliation`.
- **Scalp** (TradingHub.tsx:759-886, inline): "Scalp Live — Signal Screen" over `/api/v2/scalp/live`; GO/WAIT/NO-GO, grades, catalyst-verified prime setups, RVOL, social-scout pills. Related: `ScalpStopMonitorCard.tsx`.
- **Broker Orders** (`src/components/BrokerOrders.tsx`, rendered TradingHub.tsx:589): "ACTIVE TRADER · DRAFT BUILDER" — Stage 2a, marked DORMANT (BrokerOrders.tsx:7); DRAFT intents only. APIs: `/api/v2/broker-orders/{capabilities,drafts,events,activity,shadow-recon,preview,explain,approval-status,pilot/status,pilot/preflight,request-approval,approve,reject,delete,pilot/execute,pilot/cancel,pilot/arm|disarm,suggest-levels}`, `/api/v2/schwab/quotes`, `/api/v2/brokers/schwab/token-health`. `ActiveTraderPanel` at BrokerOrders.tsx:440-629.
- **Entry Desk** (`src/pages/ManualTosDesk.tsx`): `/api/v2/broker-orders/drafts?broker=schwab`, `/api/v2/broker-orders/activity`, `/api/v2/paper-proposals`, `/api/v2/watchlist/items`, `/api/v2/symbol-cards`, `/api/v2/schwab/accounts-live`, `/api/v2/watchlist/summary`, `/api/v2/execution/current-state`, `/api/v2/entry-desk/{automation,technical-grades,promote}`.
- **Proposals** (`src/components/BrokerProposals.tsx`): `/api/v2/broker-proposals` + ~18 action sub-endpoints (bulk-action, resize-to-cap, manual-submit, route/confirm, validate, refresh-prices, oversight queues, etc.).
- **Execution quality** (TradingHub.tsx:615-720): TCA over `/api/v2/execution-quality`; a separate journal feed `/api/v2/journal/execution-quality` (JournalHub.tsx:210).
- **Broker Recon** (TradingHub.tsx:721-758): `/api/v2/broker-reconciliation` ("DB vs Alpaca"); plus `broker-orders/shadow-recon` and `ShareReconciliationModal.tsx`.
- **Journal** (`src/pages/JournalHub.tsx`): 14 tabs; `/api/v2/automated-trade-journal`, `/api/v2/journal` (+ closed-trades/lessons, execution-quality, edge-analytics, tagging-queue, ai-critique, review, export, …), `/api/v2/paper-trade-readiness`, `/api/v2/rec-intel/outcomes`.

## 1.4 Build & deploy

- Build output `apps/command-center-v3/dist/`; footer BuildMarker reads `/v3/build-meta.json` (App.tsx:34-47, 183).
- Served by `scripts/portfolio_server.py` (plain http.server): `/` 302→`/v3/`; `/v3/*` from dist with SPA fallback (portfolio_server.py:1489-1511); server injects `cc-boot.js` + cache-bust (1459-1531); cc-boot forces one-time client reload on new `ui_version`. v2 frozen with redirect banner (1422-1459).
- CI (`.github/workflows/options-lifecycle-ci.yml:84-94`): frontend job (Node 22) runs `npm ci && npm run build` on `apps/command-center-v3/**` changes. No deploy step in CI; deploy = the running server serving `dist/`.

## 1.5 Regression tests

- `playwright.config.ts`: testDir `./e2e`, 45s timeout, serial, chromium-only, `PLAYWRIGHT_BASE_URL` (default `http://127.0.0.1:4173`).
- Specs: `portfolio-ux.spec.ts` (functional smoke: Portfolio tabs, holdings table, stop management, ticker drawer); `operator-cards-screenshots.spec.ts` (watch-card screenshots, 8 symbols); `alpaca-live-read-admin.spec.ts` (System→Admin screenshots).
- **Gap:** no Trading/Scalp/Broker-Orders/Journal/execution-quality/reconciliation e2e coverage; e2e is NOT run in CI (frontend CI job typechecks + builds only; `scripts/run_tradeai_regression.sh:79` runs build smoke only).

## 1.6 /v3-next and "active trader" references

- `v3-next`: ZERO matches anywhere in `apps/` — confirmed absent.
- "Active Trader": only the thinkorswim/Fidelity domain concept (BrokerOrders draft-builder panel and manual-ticket copy) — no next-gen frontend target exists.

UNVERIFIED (frontend): resolved dependency versions (semver ranges audited, `package-lock.json` not opened); full scope of `release-readiness.yml`; `_archive/` components.

---

# PART 2 — BACKEND SERVICES AND /api ROUTE OWNERSHIP

## 2.1 Services / entry points

Backend is **Python stdlib `http.server` + `socketserver`** — no Flask/FastAPI anywhere in the server path.

| Service | Entry file | Port | systemd unit |
|---|---|---|---|
| Main API + dashboard server | `scripts/portfolio_server.py` | 7777 (`portfolio_server.py:45`) | `config/systemd/portfolio-server.service` (live host runs system-scoped `tradeai-portfolio-server.service`) |
| Continuous trader | `linux_launchers/run_continuous.sh` | n/a | `tradeai-continuous.service` |
| Schwab stream (read-only WS client) | `scripts/schwab_stream_daemon.py` | n/a | `tradeai-schwab-stream.service` + `.timer` |
| Health agent | `scripts/health_agent.py` | n/a | `tradeai-health-agent.service` + `.timer` |
| ChatGPT OAuth proxy | `scripts/chatgpt_oauth_proxy.py` | 8646 | `chatgpt-oauth-proxy.service` |
| Grok OAuth proxy | `scripts/grok_oauth_proxy.py` | 8645 | `grok-oauth-proxy.service` |
| Scalp WS broadcast | `scripts/scalp_ws_server.py` | UNVERIFIED | unit file not found (UNVERIFIED) |
| Secrets env render | `scripts/secrets/render_env.py` | n/a | `tradeai-sm-render.service` (user) |

Hot-reloadable modules (mtime-gated by `portfolio_server.py:77-124`): `scripts/api_v2.py`, `scripts/reports_portal.py`, plus pilot submit stack + decision-authority modules reloaded with api_v2; `api_v2.py:20-30` self-heals decision modules by popping `sys.modules`.

## 2.2 Route ownership

All internal API routes owned by `scripts/api_v2.py`, dispatched through one `handle()` entrypoint (`api_v2.py:33666`).

| Prefix | Owner | Registration | Count |
|---|---|---|---|
| `/api/v2/*` GET | `api_v2.py` | `ROUTES` dict (`api_v2.py:33171-33661`) | ~477 |
| `/api/v2/*` POST/mutating | `api_v2.py` | `handle()` branches (`api_v2.py:33674`+) | ~40 |
| `/api/v2/inference*` | `inference_api.py` | delegated at `api_v2.py:33687` | sub-router |
| `/api/v3/*` internal | **NONE — 0 routes** | — | 0 |

- `/api/v3` strings in repo are all external FinancialModelingPrep URLs (`secret_validators.py:86` etc.).
- **`/api/v3/active-trader`: CONFIRMED ABSENT** (zero hits repo-wide).
- `reports_portal.py` is prose-named "v3 Reports portal" but served under `/api/v2/*` (`api_v2.py:1403-1454`).

## 2.3 Feature flags

No single feature-flag module. Four layers:
1. Env vars (`.env`): `ENABLE_TELEGRAM=true`, `ENABLE_EMAIL=false`, `ENABLE_SLACK=false`, `ENABLE_WHATSAPP=false`, `BROKER_LIVE_ENABLED=true`, `ALPACA_MODE=paper`, `DEFAULT_PAPER_ACCOUNT=alpaca_paper` (values verified live 2026-07-22), `TRADE_APPROVAL_REQUIRED_CHANNELS`, `TRADE_APPROVAL_TTL_MIN`.
2. DB `system_controls` key/value (raw SQL reads, no central accessor; fail-closed): `pilot_armed_until`, `schwab_pilot_standing_unlock`, `broker_live_enabled`, `protective_stops_enabled` (`execution_guard.py:56-96`).
3. DB kill-switch tables `kill_switch_state`/`kill_switch_audit` (scoped global/broker/account/strategy/symbol/asset_class).
4. Committed policy files/literals (`config/*.yaml|json`; gate modules deliberately avoid `os.getenv` — `pilot_caps.py:12`, `canary_gate.py`).

There is NO server-side scoped feature-flag system of the kind §16I requires — it must be built additively in Stage 1.

## 2.4 WebSocket/SSE

- `scalp_ws_server.py` (websockets/asyncio broadcast; consumer is v2 frontend `ScalpLiveFeed.tsx`); `schwab_stream_daemon.py` is an outbound WS client. No SSE found in the main API path (UNVERIFIED negative).

## 2.5 Scheduler

Cron → `run_scheduled_*.sh` wrappers (10) → Python; newer DB-backed pipeline controller (`config/pipeline_controller.bootstrap.yaml`, seeded by `seed_pipeline_controller.py --apply`; authoritative copy in DB). `scripts/pipelines/_pipeline_common.sh` defaults `DRY_RUN=1`, fail-loud `.env` sourcing, logs to `logs/pipelines/`. 454 live crontab entries (live host, 2026-07-22).

# PART 3 — DATABASE SCHEMA, MIGRATIONS, TESTS, DEPLOY

## 3.1 Migrations

**Mechanism: raw `.sql` files applied ad-hoc via `psql`. No Alembic, no migration framework, no migration-tracking table** (grep for `schema_migrations`/`migration_history`/`applied_migrations`: zero matches).

- Primary: `migrations/` — 78 flat `.sql` files, date-prefixed names (mixed `YYYY_MM_DD_slug` / `YYYY-MM-DD_slug`). Applied manually or by cron installers (OPERATIONS.md:158-161).
- Secondary/legacy: `sql/migrations/` (session-numbered), `linux_port_v2/linux/migrations/` (15 numbered + one-time JSON→PG importer `db_migrate.py`), archived phase migrations under `docs/_archive/`.
- ~20 ad-hoc `scripts/migrate_*.py` Python migration scripts (self-contained, `CREATE TABLE IF NOT EXISTS`), e.g. `scripts/migrate_broker_account_model.py`.
- **Rollback:** no per-migration DOWN. DB-level rollback = pg_dump restore (`docs/RESTORE_GUIDE.md:82,104,292`; 14 daily gzips at ~02:30 via `run_pg_backup.sh`). Crontab rollback = paired snapshot files at repo root.
- Recent 10 (by filename date): `2026_07_26_shadow_job_stages.sql`, `2026_07_25_shadow_decision_packets.sql`, `2026_07_24_research_intelligence_v2.sql`, `2026_07_23_position_transfer_history.sql`, `2026_07_22_watch_decision_refresh_v5.sql`, `2026_07_22_oversight_run_keys.sql`, `2026_07_21_redeploy_audit_log.sql`, `2026_07_21_alpaca_taxonomy_r1_registry.sql`, `2026_07_20_redeploy_analytics.sql`, `2026_07_19_redeploy_data_integrity.sql`. (Filename dates run ahead of commit date.)

## 3.2 Schema ownership (table families)

| Family | Owners | Representative tables |
|---|---|---|
| Watchlist | `scripts/watch_*`, watch migrations | `tos_watchlists`, `tos_watchlist_members`, `watch_directives`, `watchlist_entry_plans`, `watch_decision_refresh_jobs/runs` |
| Proposals | ~25 `scripts/proposal_*.py` | `proposal_status_events`, `paper_protection_adjustment_proposals`, `decision_blueprints`, `decision_packets` |
| Orders | `scripts/brokers/*`, `2026-06-11_broker_order_intents.sql` | `broker_order_intents`, `broker_live_approvals`, `intent_state_events`, `trade_approvals` |
| Scalp | `scripts/momentum_scalp_*`, `scripts/scalp_*` | `pullback_macd_candidates/runs`, `scalp_scan_results`, `scalp_decision_outcomes` |
| Journal | ~12 `scripts/journal_*.py` | `journal_manual_entries`, `journal_session_recaps`, `journal_options_groups` |
| Hermes | `scripts/hermes_*`, `lib/hermes_*` | `hermes_discovery_candidates/clusters`, `hermes_score_history` |
| Redeploy/oversight | `lib/redeploy_*` | `redeploy_audit_log`, `deploy_oversight_runs`, `oversight_run_keys` |
| Schwab/broker sync | `scripts/brokers/*`, schwab migrations | `schwab_positions_live`, `schwab_cost_basis_lots`, `broker_oauth_tokens`, `broker_oauth_token_audit` |

**Active-Trader-adjacent table existence (verified in repo AND against live DB, 657 public tables):**

| Concept | Status |
|---|---|
| Session authorizations | NOT FOUND (closest: `broker_oauth_tokens`/`_audit`) |
| Broker capabilities | PARTIAL — `broker_capability_checks` (`scripts/migrate_broker_account_model.py:85`; exists in live DB) |
| Rejection events | NOT FOUND as dedicated table (rejections likely inside `proposal_status_events`/`intent_state_events` — UNVERIFIED) |
| Feature flags | NOT FOUND (nearest: `kill_switch_state`/`kill_switch_audit`, `llm_process_config`) |
| Notifications | NARROW — `position_transfer_notifications` only; Telegram alerting is code-driven |
| Run checkpoints | NOT FOUND (nearest: `*_runs` tables + `oversight_run_keys` for idempotency, not resumable checkpoints) |

## 3.3 Test suite

- pytest; `tests/` — 345 `test_*.py` files + `tests/fixtures/` + `tests/e2e/` (2 Node .mjs scripts, require live server — not offline-safe).
- `tests/conftest.py:29-34`: 4 live-DB standalone scripts collect-ignored (`test_broker_scaffold.py`, `test_canary_exclusion.py`, `test_canary_gate.py`, `test_two_channel_approval.py`); autouse fixture blocks live Telegram dispatch.
- CI: `.github/workflows/release-readiness.yml` (TRADE_AI_CI=1, source-only, Python 3.13: `run_release_ci_equivalent.py --source-only`, `validate_schwab_write_policy.py --source-only`, `test_no_broker_write_bypass.py` — never performs broker writes); `.github/workflows/options-lifecycle-ci.yml` (postgres:17 service, 9 named lifecycle tests, SKIPPED==FAILURE, plus frontend build job; Python 3.12).
- Local mirror: `scripts/run_release_ci_equivalent.py` (~17 read-only validators; source-only via `--source-only` or `TRADE_AI_CI=1`, line 134).
- Offline-safe heuristic: ~314/345 test files show no DB reference (grep heuristic — UNVERIFIED per-file).

## 3.4 Deployment & rollback

- Hot-reload rule (OPERATIONS.md:172-199): ONLY `scripts/api_v2.py` and `scripts/reports_portal.py` hot-reload (mtime-gated). Everything else requires full restart.
- Restart: `systemctl --user stop portfolio-server.service` → kill orphan `:7777` listener if present (`kill -TERM` then `-9`) → start → verify single listener matches MainPID. Known SO_REUSEPORT twin-listener failure mode.
- systemd units in `config/systemd/` → `~/.config/systemd/user/`: `portfolio-server.service`, `tradeai-continuous.service`, `tradeai-schwab-stream.service/.timer`, `tradeai-health-agent.service/.timer`, `grok-oauth-proxy.service`, `chatgpt-oauth-proxy.service`, `tradeai-sm-render.service/.timer`.
  - NOTE (runtime discrepancy, live host): the running unit is **system-scoped `tradeai-portfolio-server.service`** (MainPID 853265, WorkingDirectory=production checkout, User=johnclaw), while OPERATIONS.md documents user-scoped `portfolio-server.service`. Recorded as a doc-vs-runtime mismatch.
- App-code rollback: no scripted blue/green; git + restart. DB rollback: pg_dump restore.

## 3.5 Python environment (root `requirements.txt`; no pyproject/setup.py)

- `openai==2.30.0`, `anthropic==0.87.0`; `httpx==0.28.1`, `requests==2.33.1`, `aiohttp==3.13.4`, `websockets==16.0`
- `psycopg2-binary==2.9.12`; NO pgvector client; NO Flask/FastAPI (server is stdlib http.server)
- Brokers: `schwab-py==1.5.1` ("read-only Schwab transport; writes fenced"), `snaptrade-python-sdk>=11`; NO alpaca SDK pin (raw HTTP — UNVERIFIED); **NO futu/moomoo SDK**
- `pandas==3.0.2`, `numpy==2.4.4`, `playwright==1.60.0`, `pydantic==2.12.5`, `peewee==4.0.4` (scope UNVERIFIED)
- Python: 3.14.4 in production venv (verified live); CI uses 3.12/3.13.

## 3.6 Docs

- Canonical index: `docs/DOCUMENTATION_INDEX.md` (2026-07-21); Tier-1: `docs/MASTER_SYSTEM_DOCUMENTATION.md`, `A1A.md`, `LIVE_SYSTEM_FACTS.md`, `CHEAT_SHEET.md`, `RESTORE_GUIDE.md`, `OPERATIONS.md`, `ARCHITECTURE.md`, + reference DOCX `docs/project/Trade_AI_v12_Reference_Architecture.docx`.
- Audit tool: `scripts/docs_audit.py` (read-only classifier → `docs/_audit/`).

UNVERIFIED (Part 3): web framework internals (stdlib-custom, not opened by DB auditor — confirmed stdlib by frontend auditor via portfolio_server.py); pgvector column absence; Alpaca SDK mechanism; rejection/checkpoint row-level storage; offline-test safety per-file; peewee scope.
