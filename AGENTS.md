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
