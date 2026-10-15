# Trade AI v12 — Restore Guide

Status:      ACTIVE
as_of:       2026-10-15T02:35:00Z (§0, re-measured); 2026-08-11T08:38:52-04:00 (§1–§11)
Measured at: §0 served 5aa61048d / origin/main 57d8fc3ff (first written at 3e9dc5e14), host ms01-openclaw;
             §1–§11 efcc51365 / not measured

> **Superseded 2026-10-14:** the model-policy banner that stood here (gemma3 = primary chat) no longer holds — local
> generative models are policy-barred (`scripts/lib/llm_task_policy.py`; AGENTS.md §12); only embeddings run locally.
> "All backup files are in the git repo" is also wrong: backups are dumps and encrypted archives under `~/db_backups`,
> `persistent-state/backups/` and Drive `Trade_AI_Backups` (§0.2). Read §0 first; §1–§11 are the 2026-08 guide.

**If you need to rebuild the system from scratch, follow this guide.**

---

## 0. Disaster recovery and failover — as of 2026-10-14

Status labels: LIVE, MERGED-NOT-SERVED, PR-OPEN, BRANCH-ONLY, PLANNED, POLICY-ONLY
(`docs/implementation/n8n-maturity/N8N_GAP_ASSESSMENT_AND_MATURITY_REVIEW_20261014.md` §0).

### 0.1 The honest position

- **One host, no failover, no UPS.** ms01-openclaw runs everything (API, n8n, Postgres, executors, bridge). There is
  no standby host and no replica. `~/power-watch/README.md` records four hard power cuts (2026-08-21, 09-10, 09-11 ×2)
  attributed to the failing 19 V DC supply; uptime since 2026-09-12 17:02. The n8n stack has never been shown to
  come back after a cold boot (WS8-06, CRITICAL). **RTO and RPO have never been stated or measured** (WS8-07).
- **Money is protected outside the host.** Resting broker stops work with the host dead (they did on 10-14, SPCX).
  The host's job in a disaster is to tell the operator and to stay out of the way; nothing in this guide places,
  changes or cancels an order (AGENTS.md §0 rules 1–2).
- **No `trade_ai` database restore has ever been drilled** (`config/backup_coverage_manifest.json` "NEVER DRILLED";
  `scripts/trade_ai_restore_drill.py` exists, NEVER_SCHEDULED; WS6-07). The n8n database restore is drilled weekly.

### 0.2 Backups (LIVE)

| What | How / when | Where | Latest receipt (2026-10-14) |
|---|---|---|---|
| `trade_ai` Postgres | `tradeai-portfolio-backup-cadence.timer` 02:30 daily → `scripts/pipelines/run_portfolio_maintenance_pipeline.sh --cadence backup` → `linux_launchers/run_pg_backup.sh` | `~/db_backups/trade_ai_<ts>.sql.gz` (one kept by `tradeai-backup-enforcer.timer`; older in `archive/`) | `trade_ai_20261014_023000.sql.gz` 2.89 GB, 02:49; receipt `persistent-state/data/runtime/portfolio_maintenance_backup_last_run.json` ok |
| Secrets/state archives | same cadence: `backup_secrets_state.sh env|memory|ops`, gpg AES-256 | Drive `Trade_AI_Backups` via `gog` | same receipt |
| Offsite DB, data, apps | same pipeline, weekly-gated | Drive | `last_db_offsite_backup.stamp` 2026-10-08 (offsite RPO ≈ 7 days, WS6-06) |
| n8n database | `tradeai-platform-maintenance-nightly.timer` 01:15 → `scripts/n8n_lab_backup.sh` (keeps 14) | `persistent-state/backups/n8n/n8n-lab-<ts>.dump` | `n8n-lab-20261014T051506Z.dump`; `n8n_lab_backup_last.json` |
| n8n restore drill | weekly timer (Sun 03:00) → `scripts/n8n_lab_restore_drill.sh` | scratch DB | `n8n_lab_restore_drill_last.json` 2026-10-11: 157/157 tables, 43 workflows, ok |
| Workflows (source of truth) | generated from git | `docs/implementation/n8n-maturity/workflows/`, `docs/implementation/n8n-parallel/workflows/generated/` | drift 18/18 OK (manual check, 02:35Z 10-15; 16 legacy + 2 fabric) |
| Releases | `scripts/cio_phase2_exact_main_deploy.sh`; disk hygiene keeps 10 | `~/trade-ai-releases/portfolio-server/<sha>-…` | CURRENT = `5aa61048d-main-exact-phase2-20261014-191424` (since 00:24Z 10-15) |
| Generated docs, memory | cron `50 23` `backup_generated_docs.sh`; `10 3` memory sync; `5 *` `run_drive_syncs.sh --apply` | Drive | never drilled |
| Inventory | `config/backup_coverage_manifest.json` (as_of 2026-10-09) | repo | holes in governance and audit state (WS6-06) |

### 0.3 Failure scenarios and the recovery path

| Scenario | Detect | Recover | Proven? |
|---|---|---|---|
| Bad release | `curl -s 127.0.0.1:7777/v3/build-meta.json`; health check in `promote` | `bash scripts/cio_phase2_exact_main_deploy.sh rollback` (restores `PREV_RELEASE`, drop-ins, pins); `docs/ops/ROLLBACK_COMMANDS.md` | yes (auto-rollback on failed promote) |
| n8n down | `tradeai-n8n-lab-watchdog.timer` (`/healthz`); heartbeat-watch stops (it runs in n8n — the notifier's fan-in age check then pages) | `docker compose` restart of `m8m-n8n` (operator, `service`/`cron` grant); cut-over lanes fall back by uncommenting their `# RETIRED … n8n-cutover` cron lines (`ROLLBACK_COMMANDS.md`); approvals fail closed | partial — restart yes, cron fallback per lane documented, never rehearsed as a set |
| n8n DB lost | restore drill receipt | `pg_restore` the newest `n8n-lab-*.dump` (drill script is the procedure); re-import workflows from git if needed | yes (weekly drill) |
| `trade_ai` DB lost or corrupt | `postgres-main-watchdog` timer; CC false-green risk (AGENTS.md 2026-09-18 ENOSPC lesson) | §3 "Restore the database from the latest dump" | **no — never drilled** |
| Disk full (`/` or `/tmp` inodes) | root-disk checks in health agent; `/tmp` inodes unmonitored (WS3-31) | `docs/runbooks/DB_RETENTION.md`, hygiene enforcer; breakers opened by ENOSPC need operator release (`scripts/n8n_dlq.py`, ledger `breakers`) | partial |
| Power loss / host death | **nothing off-box notices** (WS3-18) | power on; systemd user units and docker restart policies; then §0.4 checklist | **no — never cold-booted** |
| Broker credential compromise | — | Schwab app deactivation (done 2026-10-14); `docs/runbooks/KEY_ROTATION.md` (rotation declined by the operator for now); trading lock **LIVE, LOCKED** (#1734, `docs/runbooks/TRADING_LOCK.md`); global kill switch ON | partial |
| Full rebuild | — | `docs/runbooks/BARE_METAL_RECOVERY.md` (Drive + gpg + Bitwarden SM), then §11 below | **no — offsite decrypt has no receipt** |

### 0.4 After any restart or restore — verify, in order

1. `curl -s 127.0.0.1:7777/v3/build-meta.json` names the expected SHA; `readlink -f ~/trade-ai-releases/portfolio-server/CURRENT`.
2. `systemctl --user --failed` is empty; `docker ps` shows `m8m-n8n` and `m8m-n8n-db`; `curl -s 127.0.0.1:5678/healthz`.
3. Ledger runs resume (query in `N8N_MONITORING_AND_REMEDIATION_STANDARD.md` §0.3); fan-in and notifier receipts
   fresh (`n8n_incident_fanin_last.json`, `incident_notifier_last.json` < 10 min).
4. `python3 scripts/check_n8n_workflow_drift.py --dry-run` → 18/18 OK (or the then-current count); the fabric pair
   (`tradeai-fabric-run-lane`, `tradeai-fabric-error`) is active and published. A sub-workflow that comes back
   unpublished breaks Execute Workflow callers (n8n calls only published sub-workflows).
5. The trading lock state is what the operator expects (#1734 LIVE: locked unless a valid unlock file exists;
   `GET /api/v2/execution/kill-switches` shows the expected switches).
6. Send nothing, place nothing, change no flag; report to the operator (`docs/runbooks/INCIDENT_RESPONSE.md`).

### 0.5 Gaps (owner: operator decisions in `DECISIONS_FOR_OPERATOR.md` 8; REFACTOR_PLAN E1)

UPS; a cold-boot drill with a receipt; the first `trade_ai` restore drill; an offsite decrypt drill; a stated RTO/RPO;
an off-box dead-man so host death is noticed.

---

## 1. Core Services

| Service | How to Start | Config Location |
|---|---|---|
| Portfolio server | `nohup .venv/bin/python scripts/portfolio_server.py &` | scripts/portfolio_server.py |
| Trade AI continuous runner | `systemctl --user start tradeai-continuous.service` | ~/.config/systemd/user/tradeai-continuous.service |
| OpenClaw gateway | `openclaw gateway restart` | ~/.openclaw/openclaw.json |
| Ollama LLM | `ollama serve` (auto-starts) | Model: qwen3:14b |
| PostgreSQL | `sudo systemctl start postgresql` | DB: trade_ai, user: trade_ai |

## 2. Critical Environment Variables — Bitwarden SM is the source of truth (2026-07-21)

**`.env` no longer exists on disk.** All env secrets (106 keys) live in the Bitwarden
Secrets Manager project **`trade-ai-prod`** and are rendered to a tmpfs cache
(`/run/user/<uid>/tradeai/env`, 0600) by `scripts/secrets/render_env.py` — scheduled via
`tradeai-sm-render.timer`. Processes load them through `scripts/lib/env_bootstrap.py`,
which falls back to `.env` / `.env.pre-sm-migration` if Bitwarden is unreachable.

**Restore order:**
1. Restore `~/.openclaw/credentials/` from the **apps** backup → brings back
   `bws_read_token` / `bws_write_token` (machine tokens). If lost, mint new machine
   tokens in the Bitwarden web console (they are NOT recoverable any other way).
2. Install the `bws` CLI to `~/.local/bin/bws` (bitwarden.com/help/secrets-manager-cli —
   the binary is not in any backup).
3. `python scripts/secrets/render_env.py --now` → verify key count in the render output.
4. Restore `config/broker_credentials.env` from the **env** backup (holds
   `SCHWAB_TOKEN_ENC_KEY`, the Fernet key for the encrypted broker OAuth tokens in
   Postgres; also mirrored in SM — restore = write the value back to that file, chmod 600).
   Without it the DB token rows are undecryptable — recover by running one Schwab
   auto-reauth instead (see §2b).

### 2b. Schwab OAuth reauth (manual-first — 2026-08-11)

Schwab refresh tokens last **7 days from true browser login** (rotation does not extend the
true clock). **Preferred restore / renew path:**

1. Open Command Center **Ops → Schwab Reauth** (`/v3/system/schwab-reauth`)
2. **Request renewal URL** → log in on phone + 2FA
3. Paste full `https://127.0.0.1/?code=…` address-bar URL → **Submit**

APIs: `GET /api/v2/brokers/schwab/reauth-url`, `POST /api/v2/brokers/schwab/exchange-code`.
Requires portal env: `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_CALLBACK_URL=https://127.0.0.1`.
Telegram paste of the same redirect URL still works as backup.

Browser auto-login is **disabled by default** (cron commented out; script is notify-only).
Emergency Chromium path: `scripts/schwab_auto_reauth.py --browser --now` (needs xvfb,
playwright chromium, Bitwarden `SCHWAB_LOGIN_ID`/`SCHWAB_LOGIN_PASSWORD` via
`scripts/secrets/store_schwab_login.py`). Browser profile
`data/runtime/schwab_browser_profile/` is NOT backed up. Full runbook:
`docs/SCHWAB_AUTO_REAUTH.md`.

**Quoting rule (legacy env files):** Values containing parentheses, spaces, or semicolons MUST be
wrapped in single quotes. This includes `FINVIZ_USER_AGENT` and `FINVIZ_COOKIE`.
python-dotenv strips quotes automatically; direct `.env` parsers use `.strip("'\"")`.

```
DB_PASSWORD=<your_password>
FINNHUB_API_KEY=<key>
FMP_API_KEY=<key>
FINVIZ_COOKIE='<full_elite_session_cookie>'
FINVIZ_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...'
YOUTUBE_API_KEY=<key>
ALPHA_VANTAGE_API_KEY=<key>
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_CHAT_ID=<id>
XAI_API_KEY=<key>
# Optional:
#FRED_API_KEY=
#BENZINGA_API_KEY=
#BRAVE_SEARCH_API_KEY=
#TWITTER_BEARER_TOKEN=
```

## 3. Backup topology & restore (current as of 2026-06-15)

Four independent backup streams cover the full system. **The legacy `backups/db/` location is RETIRED** —
do not look there.

| Stream | What | Where | Schedule | Retention |
|---|---|---|---|---|
| **SQL (full PostgreSQL)** | `pg_dump` of `trade_ai` (gzip, ~1.1 GB/day, 300+ tables) | **`/home/johnclaw/db_backups/trade_ai_YYYYMMDD_HHMMSS.sql.gz`** | systemd cadence daily ~02:30 (`run_pg_backup.sh`) | **14 daily** dumps (`-mtime +14`) |
| **Secrets / .env** | `.env` + `.env.bak*` bundled, GPG AES-256 encrypted | Google Drive **Trade_AI_Backups** (`1GYbZyM8nTfwuh-h2EsWTxbMpXlEUA6Qi`) | daily (`backup_secrets_state.sh env`) | rolling window |
| **Data/state** | `data/` state, GPG-encrypted | Google Drive **Trade_AI_Backups** | weekly-gated (≥6 days) | rolling window |
| **Code + docs** | the whole repo | GitHub `PatsKiller/tardeai` (private) + Drive docs mirror (`Trade_AI_Docs_v2`, hourly) | every commit / hourly | git history |

Orchestration: systemd user timer **`tradeai-portfolio-backup-cadence.timer`** runs the
`run_portfolio_maintenance_pipeline.sh --cadence backup --apply` pipeline (steps: `portfolio_backup` (pg) +
`secrets_backup_env` daily, `secrets_backup_data` weekly-gated). Monthly verify: `backup_verify.py`
(`0 6 1 * *`).

### Run a fresh backup on demand
```bash
bash linux_launchers/run_pg_backup.sh                          # SQL dump → /home/johnclaw/db_backups/
bash scripts/backup_secrets_state.sh env                       # encrypt .env → Drive Trade_AI_Backups
# or the full cadence (pg + secrets):
bash scripts/pipelines/run_portfolio_maintenance_pipeline.sh --cadence backup --apply
```

### Restore the database from the latest dump
```bash
DB_PW=$(grep '^DB_PASSWORD=' .env | cut -d= -f2)
LATEST=$(ls -t /home/johnclaw/db_backups/trade_ai_*.sql.gz | head -1)
gunzip < "$LATEST" | PGPASSWORD="$DB_PW" psql -h localhost -U trade_ai trade_ai
```

### Restore secrets/.env from the encrypted offsite backup
```bash
# pull the newest env_backup_*.tar.gz.gpg from Drive Trade_AI_Backups, then:
PASS=/home/johnclaw/.openclaw/credentials/env_data_backup.pass      # passphrase also in the password manager
gpg --batch --pinentry-mode loopback --passphrase-file "$PASS" -d env_backup_YYYYMMDD_HHMMSS.tar.gz.gpg \
  | tar xz                                                            # restores .env in place
```

---

## 4. Cron Jobs (restore with `crontab /path/to/crontab_backup`)

Current crontab has ~46 entries. Key ones:
- `*/15 6-19 * * 1-5` — Agent processing (market hours)
- `*/5 20-23 * * 1-5` — Agent processing (overnight)
- `0 5 * * 1-5` — Alex daily scan
- `30 6 * * 1-5` — News ingestion (Yahoo + Finnhub + Google News)
- `0 19 * * 1-5` — YouTube transcript auto-discovery
- `0 20 * * 1-5` — Overnight batch + SEC Form 4 ingestion
- `0 21 * * 1-5` — Auto-research
- `30 9 * * 0` — Watchlist hygiene
- `0 23 * * *` — Deep overnight LLM window (gemma3-overnight)
- `0 16 * * 5` — Friday extended deep LLM window (200 jobs)
- `0 10-16 * * 1-5` — Data gap resolver (hourly market hours)
- `0 18 * * 1-5` — Data gap resolver pre-overnight sweep
- `0 8 * * 0` — Data gap resolver weekly audit
- `0 8 * * 1-5` — Alert digest morning brief
- `0 16 * * 1-5` — Alert digest evening brief

Export: `crontab -l > crontab_backup.txt`

## 4. Systemd Services

| File | Purpose |
|---|---|
| `~/.config/systemd/user/tradeai-continuous.service` | Trade AI scalp runner (4-11 AM) |
| `~/.config/systemd/user/tradeai-continuous.timer` | Timer trigger |
| `~/.config/systemd/user/aegis-overnight.service` | Aegis overnight scan |
| `~/.config/systemd/user/aegis-surveillance.service` | Aegis morning surveillance |
| `~/.config/systemd/user/portfolio-daily.service` | Daily portfolio pipeline |
| `~/.config/systemd/user/recovery-watch.service` | Recovery watch daily |

Restore: `systemctl --user daemon-reload && systemctl --user enable --now tradeai-continuous.timer`

## 5. OpenClaw Configuration

| File | Purpose |
|---|---|
| `~/.openclaw/openclaw.json` | Gateway config, agent list, model defaults, memory settings |
| `~/.openclaw/agents/steph/agent/SOUL.md` | Steph personality + portfolio context |
| `~/.openclaw/agents/aegis/SOUL.md` | Aegis surveillance personality |
| `~/.openclaw/cron/jobs.json` | 3 OpenClaw cron jobs (evening scan, weekly alloc, monthly income) |
| `~/.openclaw/workspace-steph/` | Steph workspace |
| `~/.openclaw/workspace-aegis/` | Aegis workspace |

Key settings in openclaw.json:
- `memorySearch.enabled: true`
- `gateway.port: 18789`
- Models: ollama/qwen3:14b (primary) → openai/gpt-5.4-mini → anthropic/claude-sonnet-4-6

## 6. Database Tables (143)

Critical tables to verify after restore:
- `ticker_strategy_classifications` — 55 active symbols
- `watchlist_agent_results` — 198 agent analyses
- `agent_handoffs` — 110 handoffs, 32 escalations
- `news_articles` — 2,787 articles, 50 sources
- `youtube_transcripts` — 12 transcripts (cleaned + summarized)
- `personal_situation` — 18 keys (SSDI, MFS, Medicare, income targets)
- `personal_tax_history` — 2025 + 2026 tax years
- `tax_events` — conversions, dividends, trust transfers
- `cio_decisions` — 55 proposed
- `decision_outcomes` — 88 tracked
- `daily_system_metrics` — trending data
- `sec_form4` — 4 insider filings
- `deep_overnight_llm_queue` — overnight gemma3 job queue
- `deep_overnight_llm_results` — gemma3 output store
- `data_gap_registry` — gaps detected from gemma3 overnight outputs
- `gap_resolution_outcomes` — measures whether resolutions improved output
- `alert_dispatch_log` — three-tier alert classifications and dedup decisions
- `digest_queue` — aggregated alerts pending morning/evening digest
- `content_embeddings_qwen3_test` — Phase 2B parallel embedding index (test only)
- `market_quotes` — yfinance data
- `fundamental_data` — Alpha Vantage metrics

## 7. Key Scripts (dependencies)

| Script | What It Does | Key Dependencies |
|---|---|---|
| `content_scoring.py` | Unified scoring + tagging | None |
| `intel_query.py` | Agent intelligence query | content_scoring, sec_data_ingest, external_market_data_ingest |
| `agent_collab.py` | Cross-agent collaboration | None |
| `process_watchlist_agent_jobs.py` | Agent processing + synthesis | llm_router, content_scoring, intel_query, agent_collab |
| `alex_retirement_advisor.py` | Alex retirement analysis | intel_query, agent_collab, llm_router |
| `run_alex_daily.py` | Daily/weekly/monthly automation | alex_retirement_advisor, llm_router |
| `telegram_smart_alerts.py` | 6 proactive alert types | alex_retirement_advisor, telegram_alert |
| `news_ingestion.py` | Yahoo + Finnhub + Google News | content_scoring |
| `youtube_transcript_ingest.py` | YouTube video transcripts | content_scoring, youtube-transcript-api |
| `transcript_processor.py` | Clean + summarize + sub-tag | llm_router, content_scoring |
| `sec_data_ingest.py` | SEC EDGAR Form 4 | content_scoring |
| `external_market_data_ingest.py` | yfinance + Alpha Vantage + FRED | yfinance |
| `overnight_batch.py` | 8 PM metrics + stale refresh | process_watchlist_agent_jobs |
| `auto_research.py` | Conflict resolution research | llm_router, intel_query, web_research |
| `system_preflight_check.py` | 23-point health check | All of the above |

## 8. Preflight Check (run after any restore)

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
python3 scripts/system_preflight_check.py
```

Must pass 21+ of 23 checks. `portfolio-server.service` (user systemd on :7777) should be **active** — see
`docs/infra/POST_REBOOT_RECOVERY_2026_07_02.md` if orphan/adopt churn after OS upgrade.

## 9. Launcher Scripts

| File | Purpose |
|---|---|
| `linux_launchers/run_continuous.sh` | Trade AI runner launcher (sources .env, runs preflight, starts runner) |

## 10. Config Files

| File | Purpose |
|---|---|
| `assets/screeners.yaml` | Finviz screener URLs (MUST use /export not /export.ashx) |
| `config/agents_sec_interaction.yaml` | Agent SEC data interaction rules |
| `config/agents_data_sources.yaml` | Agent data source rules (if exists) |

---

## 11. Backup File Locations (all in git repo)

```
~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/
├── .env                                    ← API keys, DB password, cookies (NOT in git — manual restore)
├── crontab_backup.txt                      ← Full crontab (restore: crontab crontab_backup.txt)
├── /home/johnclaw/db_backups/             ← SQL dumps (~1.1 GB/day, 14-day retention) — NOT in git
│   └── trade_ai_YYYYMMDD_HHMMSS.sql.gz     ← latest = newest mtime (restore: gunzip | psql)
│   (Drive Trade_AI_Backups holds the daily GPG-encrypted .env + weekly data state)
├── backups/
│   ├── openclaw/
│   │   ├── openclaw.json                   ← Gateway + agents + models config
│   │   ├── jobs.json                       ← 3 OpenClaw cron jobs
│   │   ├── steph_SOUL.md                   ← Steph personality
│   │   └── aegis_SOUL.md                   ← Aegis personality
│   └── systemd/
│       ├── tradeai-continuous.service      ← Trade AI runner service
│       └── tradeai-continuous.timer        ← Timer trigger
├── assets/
│   └── screeners.yaml                      ← Finviz screener URLs (MUST use /export)
├── config/
│   └── agents_sec_interaction.yaml         ← Agent SEC data rules
├── linux_launchers/
│   └── run_continuous.sh                   ← Runner launcher (sources .env, runs preflight)
├── scripts/
│   └── system_preflight_check.py           ← 23-point health check
└── docs/
    ├── RESTORE_GUIDE.md                    ← This file
    └── TRADE_AI_V12_SYSTEM_BIBLE_V2_33.md  ← Latest Bible
```

### What is NOT in git (must restore manually):
- `.env` file (API keys, passwords — restore from the daily GPG-encrypted backup on Drive Trade_AI_Backups, or a secure copy)
- PostgreSQL data (restore from the newest `/home/johnclaw/db_backups/` dump — see §3)
- OpenClaw live configs (restore from `backups/openclaw/` to `~/.openclaw/`)
- Systemd services (restore from `backups/systemd/` to `~/.config/systemd/user/`)
- Crontab (restore: `crontab crontab_backup.txt`)

### Full Restore Sequence:
```bash
# 1. Clone repo
git clone <repo_url>
cd trade-ai-v12-rebuild/trade-ai-v12-rebuild

# 2. Restore .env (from your secure backup)
cp /path/to/secure/.env .env

# 3. Install Python deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt  # or pip install psycopg2 yfinance requests pyyaml youtube-transcript-api

# 4. Restore DB (newest dump from the active location; legacy backups/db/ is retired)
DB_PW=$(grep '^DB_PASSWORD=' .env | cut -d= -f2)
LATEST=$(ls -t /home/johnclaw/db_backups/trade_ai_*.sql.gz | head -1)
gunzip < "$LATEST" | PGPASSWORD="$DB_PW" psql -h localhost -U trade_ai trade_ai

# 5. Restore crontab
crontab crontab_backup.txt

# 6. Restore OpenClaw
cp backups/openclaw/openclaw.json ~/.openclaw/
cp backups/openclaw/jobs.json ~/.openclaw/cron/
cp backups/openclaw/steph_SOUL.md ~/.openclaw/agents/steph/agent/SOUL.md
cp backups/openclaw/aegis_SOUL.md ~/.openclaw/agents/aegis/SOUL.md

# 7. Restore systemd
cp backups/systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tradeai-continuous.timer

# 8. Start services
nohup .venv/bin/python scripts/portfolio_server.py &
openclaw gateway restart

# 9. Verify
python3 scripts/system_preflight_check.py
```
