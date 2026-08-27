# Trade AI Agent Instructions

Before performing any work in this repository, read and obey:

`./AI_WORK_POLICY.md`

It is the canonical engineering, Git, CI-cost, deployment-boundary and
remote-synchronization policy for this repository.

A local checkpoint means `git commit`, not `git push`.

Do not remotely push, open/update PRs, or trigger GitHub CI merely as part of
ordinary iteration.

If there is a conflict, use the safer/more restrictive instruction.

---

# AGENTS.md — runtime notes

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
- **A red CI check is not always a test failure.** If a job reports `failure` with **0 steps, an empty
  `runner_name`, a 2–5 s duration, and `--log-failed` returning nothing**, the job was *rejected before it
  started* — a billing/quota block, never a code problem. Check with
  `gh api "repos/PatsKiller/tardeai/actions/runs/<id>/jobs" --jq '.jobs[]|{name,conclusion,steps:(.steps|length),runner:.runner_name}'`
  and confirm via `runs/<id>/timing` → `billable.UBUNTU.total_ms == 0`. **Do not debug the diff.** This
  cost 68 min and 13 misdiagnosed PRs on 2026-08-27 — see
  [`docs/ops/GITHUB_ACTIONS_QUOTA_INCIDENT_2026-08-27.md`](docs/ops/GITHUB_ACTIONS_QUOTA_INCIDENT_2026-08-27.md).

### Repository visibility is a CI invariant — do not change it

**`tardeai` stays public.** Public repos get unlimited free GitHub-hosted Actions minutes; a private repo on
a personal account gets 2,000 min/month, and this repo's 14 workflows exhaust that in a single busy merge day.
When they run out, every job fails with the misleading signature above.

- Never flip visibility as a cleanup or session-close step. It is also standing operator policy (2026-07-18)
  that this repo remains public.
- If it must ever go private, set a non-zero Actions spending limit **first**.
- Restore with `gh api -X PATCH repos/PatsKiller/tardeai -F private=false`, then re-trigger the rejected runs
  (`gh run rerun <id>` per run) — rejected runs do not retry themselves.

### Deployment rules — data freshness

**The pipeline writes to the canonical source tree; the server reads from the release directory.
Never let them diverge.** The data pipeline (repricer, moomoo sync, portfolio_loader, orchestrator)
writes to `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/`. The live server reads
from `~/trade-ai-releases/portfolio-server/CURRENT/data/`. If the release has its own stale copies,
the header PORTFOLIO / TODAY tiles show days-old values.

- **`scripts/deploy_portfolio_server.sh`** enforces this automatically — after rsync, it replaces
  `data/portfolios/state/` and `state/data_broker/` with symlinks back to the canonical source.
- **Never manually copy** `data/portfolios/state/` into a release directory. If you create a release
  manually, symlink those directories to the canonical source immediately.
- **If the portfolio totals / top header look stale** (last_repriced is not from today):
  1. Check that `~/trade-ai-releases/portfolio-server/CURRENT/data/portfolios/state/holdings.json` is a
     **symlink** (not a regular file): `ls -la` on that path.
  2. If it's a regular file, it's a stale copy. Restore the symlink:
     ```bash
     RELEASE=$(readlink -f ~/trade-ai-releases/portfolio-server/CURRENT)
     rm -rf "$RELEASE/data/portfolios/state"
     ln -s /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state "$RELEASE/data/portfolios/state"
     systemctl --user restart portfolio-server
     ```
  3. The `portfolio_server.py` startup log prints a CRITICAL warning if `holdings.json` is more than
     7 days old at boot — check `logs/portfolio_server.log`.
- **The `state/data_broker/portfolio_snapshot.json`** is a 45s cache aggregated from holdings.json.
  If the symlinks are correct but the snapshot is stale, delete it — the next `/api/v2/overview` request
  will recompute from the live holdings:
  ```bash
  rm ~/trade-ai-releases/portfolio-server/CURRENT/state/data_broker/portfolio_snapshot.json
  ```

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
