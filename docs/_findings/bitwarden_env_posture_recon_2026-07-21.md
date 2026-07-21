# RECON: Bitwarden + Env Posture Inventory (read-only)

**Date:** 2026-07-21  
**Host:** MS-01 (`johnclaw`)  
**Scope:** Metadata only — **no secret values printed**, no migrations, no `.env` edits, no Bitwarden writes.  
**Repo root:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`

---

> **Drive sync note:** Filename avoids path substrings `secret` / `credentials` / `password` because `scripts/sync-docs-to-drive.sh` excludes `*secret*` (and related) globally — this doc was renamed from `bitwarden_secrets_recon_*` so it can mirror to Drive.

## 1. Which Bitwarden exists?

| Signal | Result |
|--------|--------|
| `bw` CLI | **Present** — `/home/johnclaw/.local/bin/bw` · version **2026.6.0** |
| `bws` CLI | **Absent** (not on PATH, not under `~/.local/bin`, no npm global) |
| `vaultwarden` binary / docker / systemd | **None found** |
| Desktop / snap / flatpak Bitwarden app | **None found** on this host |
| Config dir | `~/.config/Bitwarden CLI/data.json` (mode `0600`) |
| `bw status` | Authenticated as **`john@jwwhiting.com`**, vault **`locked`**, `serverUrl: null` → **Bitwarden cloud Password Manager** (not self-hosted, not Secrets Manager) |
| Last vault sync | `2026-07-17T16:16:32Z` |
| `bws project list` | N/A (no binary) |

### Product conclusion

| Product | Present? | Notes |
|---------|----------|-------|
| **Bitwarden Secrets Manager (`bws`)** | **No** | Not installed; no machine account tooling on host |
| **Bitwarden Password Manager (`bw`)** | **Yes** | Cloud vault; session locked; human-oriented CLI |
| **Vaultwarden** | **No** | No container, unit, or local server observed |

**Design implication:** A pure `bws` project/org machine-token architecture is **not available today** without adopting Bitwarden Secrets Manager (cloud product + `bws` CLI + machine account). Default path on this host is **vault (`bw`) + render cache**, or **upgrade to Secrets Manager** as a deliberate product choice. Vaultwarden is not a factor unless you later stand it up (and even then SM is not available on VW).

**Flag-back:** `bw list` prompts for master password while locked — vault contents **not** enumerated this recon (by design: would require unlock / interactive secret handling).

---

## 2. Secrets inventory (names only)

### Live canonical file

| Path | Mode | Owner | Size | mtime |
|------|------|-------|------|-------|
| `$REPO/.env` | **0600** | johnclaw | 12159 B | 2026-07-21 14:14 |

- **Total keys:** 102  
- **Secret-ish keys** (suffix `_KEY` / `_TOKEN` / `_SECRET` / `_PASSWORD` / `_PASSWD` / `_COOKIE`, plus a few known credential-shaped names): **~30**  
- **Config / feature flags / non-secrets:** **~72**

### Grouped inventory (key **names** only)

| Group | Count | Keys |
|-------|------:|------|
| **DB** | 5 | `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` |
| **Alpaca paper / legacy** | 4 | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER_BASE_URL`, `ENABLE_ALPACA_PAPER` (+ `ALPACA_MODE` under other) |
| **Alpaca taxable (live)** | 2 | `ALPACA_TAXABLE_API_KEY`, `ALPACA_TAXABLE_SECRET_KEY` |
| **Alpaca IRA (live)** | 0 | *slots known to modal (`ALPACA_IRA_*`) but **absent** from `.env`* |
| **Alpaca paper slot names** | 0 | `ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_SECRET_KEY` **absent** — paper still on **legacy** pair |
| **Telegram** | 4 | `ENABLE_TELEGRAM`, `ERROR_NOTIFY_TELEGRAM`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (+ `TRADEAI_PROPOSAL_ALERT_CHAT_ID` in other) |
| **LLM providers** | 4 | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`, `GEMINI_API_KEY` |
| **OpenClaw** | 0 | *no `OPENCLAW_*` keys in `.env`* |
| **Schwab** | 3 | `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_CALLBACK_URL` |
| **Finviz** | 4 | `FINVIZ_API_TOKEN`, `FINVIZ_COOKIE`, `FINVIZ_NEWS_ENABLED`, `FINVIZ_USER_AGENT` |
| **Brave** | 1 | `BRAVE_SEARCH_API_KEY` |
| **CHART-IMG** | 0 | *not present* |
| **SnapTrade** | 4 | `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, `SNAPTRADE_USER_ID`, `SNAPTRADE_USER_SECRET` |
| **Market data** | 3+ | `FINNHUB_API_KEY`, `POLYGON_API_KEY`, `ALPHA_VANTAGE_API_KEY` (+ `FMP_API_KEY`, `FRED_API_KEY`, `NEWSAPI_KEY`, `YOUTUBE_API_KEY` in other) |
| **Email / SMTP** | 8 | `ENABLE_EMAIL`, `SMTP_*`, `REPORT_EMAIL_*` |
| **Other secret-ish** | — | `ADMIN_WRITE_TOKEN`, `SLACK_WEBHOOK_URL`, `TWILIO_*`, `TWOCAPTCHA_API_KEY`, … |
| **Other config/flags** | many | risk gates, LLM local knobs, paper size, routing mode, etc. |

### Full secret-ish name list (~30)

```
ADMIN_WRITE_TOKEN
ALPACA_API_KEY
ALPACA_SECRET_KEY
ALPACA_TAXABLE_API_KEY
ALPACA_TAXABLE_SECRET_KEY
ALPHA_VANTAGE_API_KEY
ANTHROPIC_API_KEY
BRAVE_SEARCH_API_KEY
DB_PASSWORD
FINNHUB_API_KEY
FINVIZ_API_TOKEN
FINVIZ_COOKIE
FMP_API_KEY
FRED_API_KEY
GEMINI_API_KEY
NEWSAPI_KEY
OPENAI_API_KEY
POLYGON_API_KEY
SCHWAB_APP_KEY
SCHWAB_APP_SECRET
SLACK_WEBHOOK_URL
SMTP_PASSWORD
SNAPTRADE_CONSUMER_KEY
SNAPTRADE_USER_SECRET
TELEGRAM_BOT_TOKEN
TWILIO_AUTH_TOKEN
TWILIO_SID
TWOCAPTCHA_API_KEY
XAI_API_KEY
YOUTUBE_API_KEY
```

### `.env` copies / backups (count & modes — **historical-keys problem**)

| Location class | Count (approx) | Modes | Risk |
|----------------|---------------:|-------|------|
| Live repo `.env` | 1 | **0600** | Canonical |
| Repo `.env.bak*` / `.env.backup*` / `.env.*.bak` | **~10** | **mostly 0664** (world-readable group/other) | **HIGH** — long-lived plaintext with historical keys |
| Worktree symlinks → live `.env` | 2 | symlink | Shared canonical |
| OpenClaw workspace `.env` / baks | several | **0664** | Stale copies outside main tree |
| `~/backups/tradeai_openclaw*` | ≥2 full `.env` | **0664** | Backup tree leak |
| `infra/searxng/.env` | 1 | 0664 | Small local service env |
| `config/broker_credentials.env` | 1 | **0600** | Separate 67 B file |
| `.env.example` / templates | several | 0664 | Names only — OK |

**Bak paths under main repo (non-exhaustive names):**

- `.env.bak_finnhub_corruption_20260703_223601` (**0600** — good)
- `.env.bak_pre_pingurl_20260604_204040` (0664)
- `.env.bak_pre_admin_token_20260604_200455` (0664)
- `.env.bak_model_policy_20260528_164534` / `_164125` (0664)
- `.env.bak_llm_safety_20260528_124117` (0664)
- `.env.backup.20260513_082028` (0664)
- `.env.alert3c.bak` (0664)
- `backups/session25/.env.bak` (0664)

**Total `.env.bak*` / `.env.backup*` style files under `/home/johnclaw`:** **~14** (locate not fully indexed; `find` depth-limited may miss deeper trees).

**Flag-back:** Live file is correctly `0600`. Most **backups are not** — they are the concrete “historical keys in backups” problem. Also, `portfolio_server` **`POST /api/env/write`** still creates **new** timestamped copies under `file_backups/env_<ts>/.env.bak-<ts>` (see §3).

---

## 3. Secrets modal backend (trace)

### Primary path (Command Center v3 System → Admin → API Keys & Secrets)

| Step | Location |
|------|----------|
| UI | `apps/command-center-v3/src/components/SecretsManager.tsx` |
| List | `GET /api/v2/admin/secrets` → `scripts/api_v2.py` ~33207 → `secrets_admin.list_secrets()` |
| Write | `POST /api/v2/admin/secrets` → `scripts/api_v2.py` ~36062 → `secrets_admin.set_secret(key, value, actor)` |
| Implementation | `scripts/secrets_admin.py` |

**Write semantics (`set_secret`, lines 116–148):**

1. Validate key name `UPPER_SNAKE` + secret suffix (or `KNOWN_CONFIG`).
2. Read entire `$REPO/.env`.
3. Replace or append one line (quoted if needed for cookies).
4. Atomic write via `mkstemp` + `os.replace` + **`chmod 0600`**.
5. `os.environ[key] = value` **only in the portfolio_server process**.
6. Audit append: `data/runtime/secrets_admin_audit.jsonl` — **key name + actor + ts only** (never value).

**Does NOT write to DB.** No `secrets` / `api_key` tables in Postgres.

### Secondary / legacy write path (flag-back)

| Path | File:line | Behavior |
|------|-----------|----------|
| `POST /api/env/write` | `scripts/portfolio_server.py` ~2167–2190 | Bulk updates; **copies full `.env` to `file_backups/env_<ts>/.env.bak-<ts>`** then rewrites live `.env` |

This path **perpetuates** bak proliferation and is a second write surface outside `secrets_admin`.

### Read / validate

- Masked list only from `.env`.
- `POST /api/v2/admin/validate-secret` — provider pings (presence/validity), not a second store.

---

## 4. Consumption pattern

### Dominant patterns

| Pattern | Prevalence | Behavior after re-render of `.env` |
|---------|------------|-------------------------------------|
| **`python-dotenv` `load_dotenv(PROJECT_ROOT / ".env")` at import/main** | **~203** scripts reference `load_dotenv` | **Live on next process start** (cron: every run) |
| **Manual line-parse of `.env` into `os.environ`** | Widespread (incl. `db_adapter._load_dotenv_if_needed`) | Same — next start |
| **`os.getenv` / `os.environ` only** (no file load) | Many helpers (e.g. `telegram_alert`, `alpaca_credentials`) | Depends on **parent** having loaded env |
| **Shell `source .env` or grep-from-`.env`** | Launchers (`run_continuous.sh`, options monitors, `backup_generated_docs.sh`, …) | Next shell invocation |
| **systemd `EnvironmentFile=` for Trade AI** | **Not used** for portfolio stack | N/A |
| **Cron** | ~**450** non-comment lines; almost all `cd $PROJ && .venv/bin/python scripts/…` | **No** global env inject — relies on script dotenv |

### Long-running process

| Process | How started | Env load | Restart required for new secrets? |
|---------|-------------|----------|-----------------------------------|
| `portfolio_server.py` (PID observed, port **7777**) | `linux_launchers/restart_server.sh` → `nohup python scripts/portfolio_server.py` | `load_dotenv` at import (~L53) + setdefault parse (~L118) | **YES** — holds process-lifetime `os.environ` |
| Modal write | `set_secret` mutates **server** `os.environ` for that one key | Immediate for **that process only** | Other workers/N/A; still restart for clean full set |

### Sample matrix (10 representative)

| Script / role | Load style | Restart vs live after re-render |
|---------------|------------|----------------------------------|
| `portfolio_server.py` / API + CC | dotenv at import | **Restart required** |
| `alpaca_stop_manager.py` (stop supervisor) | `load_dotenv` in main | **Live next cron/run** |
| `open_trade_manager.py` / ATM-ish path | `load_dotenv` at import | Next run / restart if long-lived |
| `alpaca_paper_adapter.py` | `load_dotenv` + `getenv` legacy keys | Next run |
| `alpaca_live_read_sync.py` | Via `alpaca_credentials` → **`os.environ` only** | **Live next cron** if parent env set; **must** load dotenv in process or inherit — currently **depends on env already populated** (cron does not source `.env`; credentials empty unless something loads them) |
| `brokers/alpaca_credentials.py` | `os.environ` only | Parent must load |
| `db_adapter.py` | Auto-parse `.env` for `DB_*` if password missing | **Live next import** (re-read file if password unset; if already set in process, **stale until restart**) |
| `telegram_alert.py` | `os.getenv` only | Parent must load |
| `schwab_position_sync.py` | `getenv` + fallback read `.env` lines for TG | Partial live file read for TG |
| `health_agent.py` | `load_dotenv` | Next cron run |
| Launchers (`run_options_monitor.sh`, etc.) | `source .env` | Next invocation |

### Critical flag-back: live Alpaca read path vs dotenv

`alpaca_credentials.resolve_credentials` and `alpaca_read_client` use **`os.environ` only**.  
`alpaca_live_read_sync.py` does **not** call `load_dotenv`.  

Today’s successful taxable test used a shell that **sourced** `ALPACA_TAXABLE_*` into the environment. **Unadorned cron** (`python scripts/alpaca_live_read_sync.py` alone) may see **empty keys** unless:

- a wrapper sources `.env`, or  
- the script gains `load_dotenv` / shared bootstrap.

This is a **pre-existing consumption gap**, independent of Bitwarden — migration design must include a **single bootstrap** (render → env file → every entrypoint loads it), not only a vault product.

---

## 5. tmpfs feasibility

| Mount | Size | Avail | Notes |
|-------|------|------:|-------|
| `/run` | 13G | ~13G | system tmpfs |
| `/dev/shm` | 31G | ~31G | usable; currently mostly Postgres internal |
| `/tmp` | 31G | ~31G | tmpfs |
| `/run/user/1000` | ~6.4G | — | **per-user tmpfs**, mode `700`, uid johnclaw |

**Nothing** under `/run` or `/dev/shm` currently holds Trade AI `.env` / secrets files.

**Feasibility:** **Yes** — e.g. `/run/user/1000/tradeai/env` or a dedicated `tmpfs` unit. Prefer **user runtime dir** (already `0700`) over world-traversable `/dev/shm` unless mode-locked carefully.

**EnvironmentFile pattern:** Not used by Trade AI services today; **could** be added for a future systemd unit, but cron-heavy topology still wants a **file path** scripts already know (`$REPO/.env` or symlink to tmpfs).

---

## 6. GOG keyring pattern (machine-root-secret template)

| File | Mode | Role |
|------|------|------|
| `~/.openclaw/credentials/gog_keyring_password` | **0600** | Password material for gog keyring |
| `~/.openclaw/credentials/gog.env` | **0600** | Related env snippet |
| `~/.openclaw/credentials/client_secret.json` | **0600** | OAuth client |
| `~/.config/gogcli/keyring/token:*` | **0600** | Token store |
| `scripts/sync-docs-to-drive.sh` L16 | — | `export GOG_KEYRING_PASSWORD=$(cat …/gog_keyring_password)` |

**Template for Bitwarden machine token / master unlock material:**

- Path **outside repo tree**  
- Mode **0600**, owner operator  
- Consumed by **render script only** (not by 370 trading scripts)  
- Matches recommended “one new root secret” model  

---

## Deliverable summary tables

### A. Product decision matrix

| If you choose… | On MS-01 today | Migration shape |
|----------------|----------------|-----------------|
| **Secrets Manager + `bws`** | Not installed | Adopt SM org/project + machine account + install `bws`; best fit for headless render |
| **Password Manager + `bw`** | Installed, cloud, locked | Headless unlock session or limited CLI automation; clumsier for 450 crons |
| **Vaultwarden** | Not present | Would still be vault-CLI world, not SM |

### B. Restart-required vs live

| Class | After `.env` re-render |
|-------|------------------------|
| Cron one-shots that `load_dotenv` | **Live next fire** |
| Cron scripts that only `os.environ` (e.g. bare `alpaca_live_read_sync`) | **Broken unless bootstrap fixed** |
| `portfolio_server` / long-lived | **Restart required** (except single-key modal inject into that process) |
| Shell launchers sourcing `.env` | **Live next invoke** |

### C. Flag-backs (priority)

1. **No Secrets Manager / `bws`** — design cannot assume `bws` without an install+account step.  
2. **Bak sprawl + 0664 modes** — historical keys readable; kill/shred is high ROI even before vault.  
3. **Dual write APIs** — `secrets_admin` (good) vs `POST /api/env/write` (creates more baks).  
4. **Cron does not inject env globally** — every script must load file or fail closed.  
5. **`alpaca_live_read_sync` / `alpaca_credentials` dotenv gap** — fix in same epic as render bootstrap.  
6. **Paper still on legacy `ALPACA_API_KEY`/`SECRET`** — slot names empty.  
7. **IRA keys absent**; CHART-IMG / OpenClaw names absent from `.env`.  
8. **OpenClaw + home backups** hold **0664** `.env` copies outside repo.  
9. **Vault locked** — contents unknown; treat BW vault as **unverified** inventory until operator unlock+export metadata.  
10. **Do not make protective loops call vault at 09:31** — recon confirms source-of-truth-plus-cache is the right availability model for this host.

---

## Recommended architecture alignment (recon-only opinion)

Your **source-of-truth-plus-cache** sketch fits MS-01:

- **Today’s product reality** → start from **Bitwarden Password Manager cloud + `bw`**, *or* deliberately add **Secrets Manager + `bws`** (preferred long-term, not free).  
- **Render** → write `$REPO/.env` (or tmpfs file + symlink), mode **0600**, never leave 0664 baks.  
- **Fail last-known-good + Telegram staleness** if vault unreachable.  
- **Zero script rewrites** except a **shared dotenv bootstrap** for the few env-only modules (stop/ATM already load; live Alpaca read should too).  
- **Modal** → later: write upstream + trigger re-render; today: file-only.  
- **Root secret** → same shape as `gog_keyring_password`.

---

## Explicit non-actions this recon

- No unlock of Bitwarden vault  
- No install of `bws`  
- No `.env` edits, shreds, or mode changes  
- No migration scripts  
- No secret values in this document or tool logs  

---

## Next step (for build prompt author)

Pick one:

1. **SM path:** create Bitwarden Secrets Manager project + machine account + install `bws` on MS-01, then render-from-`bws`.  
2. **Vault path:** design headless `bw` unlock + secure session + render-from-vault items (accept operational friction).  

Either way, **phase 0** can still: inventory/shred 0664 baks, fix `alpaca_*` dotenv bootstrap, and deprecate `/api/env/write` bak creator — without waiting on product choice.
