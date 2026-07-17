# Bare-Metal Recovery Runbook (2026-07-17 backup-scope audit)

Rebuild this box (ms01-openclaw) from nothing but the offsite backups. Every dependency here
is either in git, in an encrypted Drive backup, or re-pullable by name from a manifest inside
the nightly `ops_backup` (crontab, systemd units, dpkg list, pip freezes, ollama models,
pg configs, .pgpass, gog CLI auth, tool versions).

## ⚠ P0 PREREQUISITE — the one thing that must live OFF this machine
**`~/.openclaw/credentials/env_data_backup.pass`** (gpg passphrase) decrypts EVERY offsite
backup — and its only copies are on this disk and inside backups encrypted WITH IT. If the
disk dies and the operator does not hold this passphrase elsewhere, every `.gpg` on Drive is
permanently unreadable.
**OPERATOR ACTION (cannot be automated): store the passphrase in your password manager NOW.**
Recommended free manager: **Bitwarden** (bitwarden.com — free tier: unlimited items, syncs
across devices, open-source, exportable; Proton Pass free is the alternative). Two minutes:
create account → New item "TradeAI backup gpg passphrase" → paste the contents of
`~/.openclaw/credentials/env_data_backup.pass` → save. Add `gog_keyring_password` too
(secondary — Drive files are also reachable via browser login without it).

## What exists offsite (Drive folder `Trade_AI_Backups`, all gpg AES-256)
| Artifact | Cadence | Contents |
|---|---|---|
| `db_backup_*.sql.gz.gpg` | weekly | full `pg_dump` of trade_ai (~1.5GB) |
| `data_backup_*` | weekly | project `data/` state tree |
| `env_backup_*` | daily | `.env` + rotated variants (every API key) |
| `ops_backup_*` | daily | crontab · systemd user units · dpkg/pip/ollama manifests · postgresql.conf + pg_hba · .pgpass · gog CLI config+keyring · tool versions |
| `apps_backup_*` | weekly | `.openclaw` config/credentials/agents/memory/state + `nyc-dof-auction` |
| `memory_backup_*` | daily | Claude memory (also mirrored to GH `trade-ai-memory`) |

Code: GitHub `PatsKiller/tardeai` (main + `generated-docs-backup` branch) and
`PatsKiller/nyc-dof-auction` (created 2026-07-17). Docs mirror: Drive `Trade_AI_Docs_v2`.

## Scripts (2026-07-17)
- **Refresh everything now:** `bash scripts/backup_all.sh [--skip-db]` — runs every family
  (pg dump → env → memory → ops → data → db-offsite → apps), stamps the weekly gates, prints
  a per-family summary. Use before risky maintenance or a planned migration.
- **Automated restore:** `bash scripts/bare_metal_recover.sh --backup-dir <staged .gpg dir>
  --pass-file <passphrase>` — parameterized (`--project-dir`, `--db-name/--db-user`, `--fqdn`,
  `--repo-url`, `--phases`, `--dry-run`); rewrites the old absolute paths embedded in the
  restored crontab/systemd units to your chosen directories and sets TAILSCALE_HOSTNAME to
  your FQDN. Phases: fetch,code,db,secrets,wiring,llm,verify (resumable via `--phases`).
  Dry-run verified 2026-07-17 with custom dirs + FQDN.

## Recovery sequence
1. **OS**: Ubuntu 26.04 (see `tool_versions.txt` in ops_backup for exact release/kernel).
   Create user `johnclaw`.
2. **Fetch + decrypt backups**: log into Google Drive (browser) or restore gog CLI auth from
   ops_backup (`~/.config/gogcli/`). For each artifact:
   `gpg --batch --passphrase-file <pass> -d file.gpg | tar xzf -` (db: `> dump.sql.gz`).
3. **System packages**: `ops_backup/manifests/dpkg_packages.txt` — install PostgreSQL 17
   server, python3.14, git, gnupg, flock/util-linux, build tools; `node v22` (see
   tool_versions), `ollama` (curl installer).
4. **Code**: `git clone git@github.com:PatsKiller/tardeai.git ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild`
   and `nyc-dof-auction`. Python: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
   (exact pins: `pip_freeze_tradeai.txt`). Frontend: `cd apps/command-center-v3 && npm ci && npm run build`.
5. **PostgreSQL**: install v17, restore `pg_config/postgresql.conf` + `pg_hba.conf`, create
   role `trade_ai` (password from restored `.env` `DB_PASSWORD`), then
   `gunzip -c dump.sql.gz | psql -U trade_ai trade_ai`. Restore `~/.pgpass` (chmod 600).
   Re-apply role guards: `docs/runbooks/DB_HANG_PREVENTION.md` (lock/statement/idle timeouts).
6. **Secrets/state**: untar env_backup → project root (`.env`); data_backup → `data/`;
   apps_backup → `~/.openclaw` + `~/nyc-dof-auction` WIP; memory_backup → `~/.claude/projects/`.
7. **Wiring**: `crontab ops_state/crontab.txt`; copy `ops_state/systemd_user/*` →
   `~/.config/systemd/user/` then `systemctl --user daemon-reload && systemctl --user enable --now
   portfolio-server.service tradeai-portfolio-*-cadence.timer` (full unit list in timers_state.txt).
   `loginctl enable-linger johnclaw`.
8. **LLMs**: `ollama pull` each model in `manifests/ollama_models.txt` (gemma3:12b/4b/27b…).
9. **Things that CANNOT be restored from backup (manual re-auth)**:
   - **Schwab OAuth** — tokens rotate; run the reauth flow
     (`scripts/schwab_token_manager.py reauth-url <acct>`; auth is AUTO after that — never hand-edit).
   - **Alpaca / Telegram / Finnhub / etc.** — keys restore with `.env`; only revoked ones need reissue.
   - **Tailscale** — `tailscale up` and re-authorize the node.
   - **Grok/ChatGPT OAuth lanes** (:8645/:8646) — re-login once, keepalive cron maintains.
10. **Verify**: `curl localhost:7777/api/v2/health`; run `scripts/health_agent.py` (its
    backup/slot/log checks should come up clean); confirm the 02:30 cadence fires next night.

## Standing invariants
- The 02:30 `tradeai-portfolio-backup-cadence.timer` is the single owner of all backups.
- `collect_backup_health` (health agent) alerts if the cadence, any step, or the local dump goes stale.
- Restore path re-verify: quarterly, decrypt one artifact of each family (proven 2026-07-17).
