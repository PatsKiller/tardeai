# AGENTS.md

Authoritative human/agent docs live in `README.txt`, `ARCHITECTURE.md`, `OPERATIONS.md`, and `docs/`.
This file only adds durable operating notes for automated (cloud) agents.

## Cursor Cloud specific instructions

The update script (run automatically on VM startup) already refreshes dependencies:
Python venv at `.venv` (Python 3.12) with `requirements.txt` + `pytest`, and the
`apps/command-center-v3` npm deps. Below is only non-obvious context for running,
testing, and demoing the app.

### Services & how to run them

- **Backend** — `.venv/bin/python scripts/portfolio_server.py` (stdlib HTTP server, **not** Flask,
  binds `:7777`). Serves `/api/*` (delegated to `scripts/api_v2.py`) and, when built, the SPA under `/v3/`.
- **Frontend (dev)** — `npm run dev` in `apps/command-center-v3` (Vite on `:7789`, proxies `/api` → `:7777`).
  Open the dev UI at `http://localhost:7789/v3/`. Production build: `npm run build` (emits `dist/`, which the
  backend serves at `http://localhost:7777/v3/`).
- **JSON-only mode is fully supported**: with no Postgres env vars set, `db_adapter.py` falls back to JSON
  and the app runs (this matches the `--source-only` CI proof). Postgres is **optional** and only needed for
  the DB-backed test subset (see below). `data/`, `state/`, `reports/` are gitignored and start empty.

### Non-obvious gotchas

- **Holdings write guard (`MIN_TOTAL = 1_000_000`)**: every write to
  `data/portfolios/state/holdings.json` goes through `holdings_guard.protected_holdings_write`, which
  **fail-closes any portfolio total below ~$1M** (the real book is ~$1.24M). A `POST /api/import` that
  succeeds with `holdings_written > 0` but leaves `holdings.json` missing was rejected by this guard — use a
  realistic ≥ $1M portfolio when seeding/testing imports.
- **`/api/v2/overview` (and many endpoints) cache for ~60s** and read from
  `data/portfolios/state/holdings.json`, so imported data appears after the cache expires, not instantly.
- **CC v3 stale-bundle auto-reload**: the SPA (`cc-boot.js` + an inline check) compares `build-meta.json`
  `ui_version` against `sessionStorage` and does a one-time full reload — a **black screen with a spinning
  white cube**. This is expected, not a crash. It recurs more on the raw Vite dev server (`:7789`); the
  backend-served built bundle (`:7777/v3/`) is more stable for screenshots/video. Rebuild `dist` after UI edits.
- **Backend hot-reload covers only `api_v2.py` and `reports_portal.py`.** Editing any other module
  (`portfolio_loader.py`, `account_policy.py`, the server itself, etc.) requires a full server restart.
- **`pytest` is not in `requirements.txt`** (CI installs it separately); the update script adds it to `.venv`.
- **A minimal `.env`** (JSON-only, `ENABLE_TELEGRAM=false`) is enough for local dev; leaving `DB_*` unset
  selects JSON-only mode. Real API keys / Postgres / Ollama are only needed for background LLM + broker work.

### Lint / test / build commands

- **Frontend lint+build**: `npm run build` (runs `check_design_tokens.sh` design-token guard +
  `test_chip_scope.mjs` + `tsc` + `vite build`). Guard only: `npm run design:guard`.
- **Release/readiness proof (deterministic, read-only, no DB, no broker writes)**:
  `TRADE_AI_CI=1 .venv/bin/python scripts/run_release_ci_equivalent.py --source-only`.
- **Python tests**: `.venv/bin/python -m pytest tests/<file>.py`. The deterministic subset runs without a DB;
  tests named `*real_postgres*` and the options-lifecycle suite require Postgres (`DB_*` env + `psycopg2`),
  matching `.github/workflows/options-lifecycle-ci.yml` (postgres:17 service).
- **Node e2e** (`tests/e2e/*.mjs`, root `package.json`) need Playwright/Puppeteer/`canvas` and a running
  server; the root `npm install` (with `canvas` native build deps) is intentionally left out of the update
  script — install it on demand if you need those e2e tests.

## Data sources & the Data Broker

A 2026-07-31 audit (`docs/DATA_ARCHITECTURE_AUDIT_2026_07_31.md`) found ~30 external sources feeding
~55 ingestion scripts with heavy duplication — 6+ parallel "last price" pipelines, 8–10 independent
RSI/SMA/ATR implementations, 10 distinct "catalyst" definitions, ~83 independent `holdings.json` loads
inside `api_v2.py`. The fix is `config/data_registry.yaml` — the single catalog of every data type, its
authoritative producer/store, TTL, authority rank, and every known consumer (page + alert + pipeline
script) — plus `scripts/lib/data_broker/registry.py`, which serves it and runs a duplication/coverage
check. Read the live state via the **Data Management page** (System hub → **Data** tab, `/v3/data`
redirects there) or straight from the API: `GET /api/v2/data/registry`, `GET /api/v2/data/coverage`,
`GET /api/v2/data/matrix`.

### Where sources connect

- **Brokers** (positions/fills, gated by `holdings_guard`): Schwab (OAuth, `schwab_transport.py`), Alpaca
  (REST, paper + live-read), SnapTrade (Fidelity bridge), Moomoo/Futu (local OpenD TCP, read-only).
- **Market data / fundamentals**: Finviz Elite (7 capabilities — screeners/enrichment/news/charts/sector
  perf), yfinance/Yahoo, Alpaca market data, Polygon, Finnhub, FMP, Alpha Vantage, FRED, SEC EDGAR.
- **News/social**: Yahoo RSS, Google News RSS, Finviz news, Benzinga, NewsAPI, StockTwits, Reddit, X,
  YouTube (Data API + transcripts), DuckDuckGo, SearXNG (`:18888`).
- **LLM/research lanes**: Grok + ChatGPT via local OAuth proxies (`:8645`/`:8646`), Claude (metered,
  escalation only), local Ollama (`:11434`) — all feed `hermes_research_intelligence`.
- Credential **names** for all of the above live in `config/agents_data_sources.yaml` (agent-facing view)
  and the registry; **values** are Bitwarden-only (see the Bitwarden section below) — never read/print a
  resolved secret to satisfy a data-source question, look up the key name instead.

### Canonical store per domain (read these, don't recompute)

| Domain | Canonical producer | Canonical store |
|---|---|---|
| Last price | `market_quote_provider.get_best_quote` | `market_quotes` table |
| Daily OHLCV | `price_db_sync.py` | `ticker_prices` table |
| RSI/SMA/MACD/ATR/RVOL | `indicator_engine.py` | `indicator_confluence_cache` table |
| Catalyst verification | `catalyst_enrichment.py` + `scoring.py` | `catalyst_events.verified` / `.confidence` |
| Share counts | broker syncs, via `holdings_guard.protected_holdings_write` | `data/portfolios/state/holdings.json` |
| Analyst rollup / detail | `pro_analyst_fetch.py` | `pro_analyst_pills_latest.json` / `analyst_consensus` table |
| Source liveness | `data_source_report.py` + `source_maturity.py` | `data_source_health` table |

**Authority hierarchy** where more than one source could answer the same question: Schwab/Alpaca
realtime > Polygon/Finnhub > FMP > yfinance > Finviz (cached/context) for quotes; Schwab = contract facts
(cost basis, lots) and `holdings.json` = share counts, always — brokers are never overridden by a
scrape. Finviz `recom` (1–5) is **not** Street analyst consensus — see
`scripts/lib/analyst_rating_canonical.py` and use `pro_analyst_pills_latest.json` for consensus.

### The rule for new data sources/types

**Any new data source or new data type MUST add an entry to `config/data_registry.yaml`
(producer/store/TTL/authority + at least one consumer row) and be served through that canonical
producer/store — do not add a new ad-hoc `yfinance`/scrape/local-recompute path.**
`scripts/lib/data_broker/registry.py:check_coverage()` is the enforcement: it flags (a) deprecated/ad-hoc
producers that are still present in the repo (migration not done) and (b) any matrix row whose
`data_type` isn't a real registry entry, or any data type with zero listed consumers (registry drifted
from reality). Run it standalone: `python3 -m scripts.lib.data_broker.registry` (add `--strict` in CI to
fail on dangling refs). If you're adding a page or an alert that reads an existing registered data type,
add its row under `consumers.pages` / `consumers.alerts` / `consumers.pipeline_scripts` in the same PR —
that's what keeps the Data Management page's matrix honest.

## Live host (ms01-openclaw) deployment gotchas

The live `portfolio-server` runs from a **SHA-pinned release directory**, not this working tree:
`~/trade-ai-releases/portfolio-server/<sha>-<label>/` (find the current one with
`readlink -f /proc/$(pgrep -f portfolio_server.py | head -1)/cwd`). Editing files in the repo has **zero
effect on the live server** until they're copied into that release dir and the service is restarted —
hot-reload covers only `api_v2.py`/`reports_portal.py`; every other module (`operations.py`,
`agent_runtime_dispatch_boot.py`, `trigger_intake.py`, etc.) needs
`systemctl --user restart portfolio-server.service`.

### Bitwarden secret naming vs. code expectations

- The rendered tmpfs env is at `/run/user/$(id -u)/tradeai/env` (`render_env.py --now` refreshes it; this
  repo's `.venv` doesn't exist — that command must run from `trade-ai-v12-rebuild`'s venv or wherever the
  real one lives).
- The **LAB migrator** Bitwarden secret is named `LAB_DSN`, not `TRADE_AI_LAB_DSN`. But
  `migrations/agentic_runtime/apply.sh` reads `$TRADE_AI_LAB_DSN` — export it explicitly:
  `export TRADE_AI_LAB_DSN="$LAB_DSN"`. Other real secret names on this host: `LAB_DSN_ALLOWLIST`,
  `SHADOW_DSN` (writer role, `agentic_runtime_shadow_rw`), `SHADOW_READER_DSN`.
- To find a secret's key name **without ever printing its value**:
  `awk -F= '{print $1}' /run/user/$(id -u)/tradeai/env | grep -i DSN` or
  `env | cut -d= -f1 | grep -i '^PG'`. Use `${#VAR}` to sanity-check a value is non-empty. Never `echo
  $SECRET` or paste a resolved DSN/password into a chat/transcript — if one leaks, rotate it immediately
  (mirrors `scripts/secrets/ensure_shadow_rw_dsn.py --rotate`'s pattern).

### `psql` alias trap on this host

`~/.bashrc` aliases `psql` to `psql -h 127.0.0.1 -U trade_ai -d trade_ai`. That pre-fills **both**
positional connection slots (dbname + username) before your own arguments are parsed, so *any* DSN you
pass — positional or via `-d` — gets silently reported as an "extra command-line argument ... ignored"
and it falls back to the hardcoded `trade_ai@127.0.0.1:5432` default (which then fails auth because
`~/.bashrc` also hardcodes a plaintext, likely-stale `PGPASSWORD=...`). **Always bypass with `command
psql -d "$DSN" ...`** on this host when you need a specific connection target. If a `psql` invocation
mysteriously ignores your DSN, run `type psql` first.

### Migration chain is not idempotent — don't replay it

`migrations/agentic_runtime/apply.sh --apply up` chains **every** `NNNN_*.up.sql` file in order
(0001 → 0002 → 0003 → ...). `0001_mvl.up.sql`'s `CREATE TABLE` statements have no `IF NOT EXISTS`, so
re-running the full chain once 0001/0002 already exist fails with "relation already exists." When adding
a new migration (e.g. `0003_trigger_intake.up.sql`) to an already-provisioned LAB schema, apply **only the
new file** directly: `command psql -d "$LAB_DSN" -v ON_ERROR_STOP=1 -f
migrations/agentic_runtime/000N_name.up.sql`. Also note `agentic_runtime_lab_rw`/`_shadow_rw` have
`CREATE` revoked on the schema (`0002_roles.up.sql`) — only the migrator role (`LAB_DSN`) can run DDL.

### Three deployment targets, not two — the agent-runtime timers run from a third tree

`run_once.py`, `health_monitor.py`, and `trigger_producer.py` are invoked by **systemd units** whose
`WorkingDirectory`/`ExecStart` point at `~/trade-ai-v12-rebuild/trade-ai-v12-rebuild` (the `main`-branch dev
worktree) — **not** the SHA-pinned live release tree that serves the HTTP API, and not this repo. All three
trees can independently drift. When changing anything under `scripts/agent_runtime/**`,
`scripts/agent_runtime_dispatch_boot.py`, or `config/agent_runtime_mvl.json`/`config/agent_runtime_schedules.json`,
copy to **both** the live release dir (HTTP-served readiness/operations/dispatch) **and** the dev worktree
(systemd-invoked timers), then `systemctl --user restart portfolio-server.service` for the former and just
re-run the relevant unit for the latter (no restart needed — each timer invocation is a fresh process).

### Per-agent/producer timers ship fail-closed (`AGENT_RUNTIME_OPERATOR_AUTH=0`) — a second wiring step is required

Unlike the HTTP dispatch path (wired by `deploy_operator_wiring.sh` writing
`~/.config/tradeai/agent-operator.env` + a `portfolio-server.service.d` drop-in), the systemd timer units
(`tradeai-agent-runtime@.service`, `tradeai-agent-runtime-producer.service`) hardcode
`AGENT_RUNTIME_OPERATOR_AUTH=0` in their `[Service]` block by design ("prepare-only"). Authorizing them is a
**separate, explicit** step: `install_agent_runtime_schedules.sh --execute` now also installs
`~/.config/systemd/user/{tradeai-agent-runtime@.service,tradeai-agent-runtime-producer.service}.d/10-agent-runtime-env.conf`
with `EnvironmentFile=<the same agent-operator.env>` (never a new/duplicated secret). `--rollback` removes
both drop-ins, restoring fail-closed behavior.

### `CapabilityBoundingSet=` fails hard on this host (exit 218/CAPABILITIES)

The per-agent timer template originally set `CapabilityBoundingSet=` (drop to empty) as defense-in-depth.
On this host the **user** systemd manager lacks `CAP_SETPCAP` (nested/containerized systemd), so *any*
`CapabilityBoundingSet=` value — even a non-empty allowlist — makes the unit fail before the process starts:
`Failed to drop capabilities: Operation not permitted` / `Failed at step CAPABILITIES`. Verify with
`systemd-run --user --pty --property=CapabilityBoundingSet= -- /bin/true; echo $?` (218 = broken host,
0 = fine). Fixed by removing the directive from
`config/systemd/agent_runtime/tradeai-agent-runtime@.service`; `NoNewPrivileges=true` is the load-bearing
control that remains.

### `run_once.py` needs `PYTHONPATH=.../scripts` — bare module names don't resolve via `-m scripts...`

`AGENT_RUNTIME_QUEUE_MODULE=agent_runtime_dispatch_boot` is a **bare** module name (the file lives directly
in `scripts/`). `portfolio_server.py` resolves it because it does
`sys.path.insert(0, PROJECT_ROOT / "scripts")` itself. `run_once.py`, invoked as
`python -m scripts.agent_runtime.agents.run_once`, has no such insert — only `scripts` (as a package) is on
`sys.path`, so `import agent_runtime_dispatch_boot` 404s with `No module named 'agent_runtime_dispatch_boot'`.
Fix: `Environment=PYTHONPATH=.../scripts` on the per-agent timer unit.

### `AGENT_RUNTIME_SHADOW_MODEL` must name a model actually pulled in Ollama

`shadow_fleet_provider.py`'s code default (`qwen2.5:3b`) is a placeholder — check what's actually pulled
(`curl -s :11434/api/tags`) before wiring. On this host it's `gemma3:4b`/`gemma3:12b`/`gemma3:27b`/`qwen3:8b`
etc., not `qwen2.5:3b`; an unpulled model makes every real dispatch fail closed (correct behavior, just the
wrong config). `deploy_operator_wiring.sh` writes `AGENT_RUNTIME_SHADOW_MODEL` into `agent-operator.env`
(override via env var before running it) rather than hardcoding a host-specific model into shared code.

### Generic SHADOW agents must not self-complete — that would fabricate review evidence

`MvlRuntime.complete()` raises `RuntimeError("cannot complete a run without independent review")` unless
`record_review(...)` was called by a genuinely different reviewer. The old LAB fixture provider
(`lab_watch_provider.py`) worked around this by hardcoding a canned `ReviewVerdict.CAUTION` + a fixed
finding string — exactly the synthetic-evidence pattern the real-trigger system exists to remove. The real
`shadow_fleet_provider.py` therefore does **not** call `complete()` for generic agents: it creates the real
artifact and leaves the run at `REVIEW_REQUIRED`, matching how `SentinelShadowPipeline` already behaves when
no `review_provider` is wired. Independent review/completion is a separate, later governed step (by the
agent's `reviewer_agent_id` from `definitions.py`), not something dispatch fabricates inline.
