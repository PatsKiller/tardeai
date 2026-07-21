# PHASE-0: Kill `.env` backup sprawl — handoff

**Date:** 2026-07-21 · **Host:** MS-01 · **Scope:** surgical destroy + prevention.  
**Live `.env` was never edited** (no key values changed). No secret **values** in this doc.

## 1. Inventory (before shred)

| Path | Mode | Size | mtime (approx) |
|------|------|-----:|----------------|
| `$REPO/.env.bak_finnhub_corruption_20260703_223601` | **600** | 14880 | 2026-07-02 |
| `$REPO/.env.bak_pre_pingurl_20260604_204040` | **664** | 10002 | 2026-06-04 |
| `$REPO/.env.bak_pre_admin_token_20260604_200455` | **664** | 9826 | 2026-06-04 |
| `$REPO/.env.bak_model_policy_20260528_164534` | **664** | 8034 | 2026-05-28 |
| `$REPO/.env.bak_model_policy_20260528_164125` | **664** | 8012 | 2026-05-28 |
| `$REPO/.env.bak_llm_safety_20260528_124117` | **664** | 7850 | 2026-05-28 |
| `$REPO/.env.alert3c.bak` | **664** | 7635 | 2026-05-15 |
| `$REPO/.env.backup.20260513_082028` | **664** | 7232 | 2026-05-13 |
| `$REPO/backups/session25/.env.bak` | **664** | 6890 | 2026-05-08 |
| `~/.openclaw/workspace/.env.alert3c.bak` | **664** | 7635 | 2026-05-15 |
| `~/.openclaw/workspace/.env.backup.20260513_082028` | **664** | 7232 | 2026-05-13 |
| `~/.openclaw/workspace/backups/session25/.env.bak` | **664** | 6890 | 2026-05-08 |
| `~/backups/tradeai_openclaw_light_*/.env` (full copy) | **664** | 8001 | 2026-04-21 |
| `~/backups/tradeai_openclaw_*/trade-ai-v12-rebuild/.env` | **664** | 8001 | 2026-04-19 |

**Modes found:** 13× **0664** (group+other readable), 1× **0600**.

### Git history

- `git log --all --diff-filter=A -- '*.env*'` → only **`.env.example`** / `infra/searxng/.env.example` ever **added** to git.
- Live `.env` is gitignored. **No bak files in git history.**

## 2. Destroy

- **Shredded:** **14** files via `shred -u -n 3`
- Live `$REPO/.env` **untouched** (still present)
- OpenClaw workspace live `.env` (not bak): **chmod 600** (was 664) — kept (app env), not shredded
- Post-check: **zero** remaining `.env.bak*` / `.env.backup*` under `/home/johnclaw`

## 3. Live `.env` mode

| | Mode |
|--|------|
| Before | **600** |
| After | **600** |

## 4. Prevention

| Control | Change |
|---------|--------|
| **umask** | `umask 077` added to `~/.bashrc` and `~/.profile` |
| **check_no_secrets.py** | Refuses staged paths matching `*.env.bak*`, `.env.backup*`, `.env.old*`, `dot_env` |
| **pre-commit** | Already chains to `check_no_secrets.py` via `pre-commit.chained` |
| **portfolio_server `POST /api/env/write`** | **Stopped** writing `file_backups/env_*/.env.bak-*`; in-place update + chmod 600 only; note prefers `/api/v2/admin/secrets` |
| **full_system_backup.py** | **Stopped** raw `dot_env` copy; sanitized names-only `dot_env_SANITIZED.txt` mode 600 + README |
| **secrets_admin.set_secret** | Confirms chmod 600 on final path after atomic replace |

### Creators flagged (root cause of sprawl)

1. **Manual / ad-hoc** `.env.bak_*` named copies (model policy, admin token, finnhub, pingurl) — operator scripts/session hygiene  
2. **`portfolio_server.py` `/api/env/write`** — automated full-file bak (patched)  
3. **`full_system_backup.py`** — raw `.env` → `env/dot_env` in backup staging (patched)  
4. OpenClaw workspace mirrors of the same bak names (copies of repo baks)

## 5. Current-key exposure check (hash equality, no values)

| Key name | Name in any bak? | **Current live value** matched a bak? | Rotation? |
|----------|------------------|----------------------------------------|-----------|
| `ALPACA_TAXABLE_API_KEY` | **No** (0) | **No** | **Not required** for bak reason |
| `ALPACA_TAXABLE_SECRET_KEY` | **No** | **No** | **Not required** for bak reason |
| `ALPACA_API_KEY` (paper/legacy) | Yes (12) | **Yes (12 baks)** | **Rotate paper Alpaca keys** (were world-readable while equal to live) |
| `ALPACA_SECRET_KEY` | Yes (12) | **Yes (12)** | **Rotate with paper pair** |
| `DB_PASSWORD` | Yes | **Yes (12)** | **Strongly rotate DB password** (separate runbook) |
| `TELEGRAM_BOT_TOKEN` | Yes | **Yes (12)** | **Rotate bot token** (BotFather) recommended |
| `ADMIN_WRITE_TOKEN` | Yes (2) | (not fully hashed in matrix) | Review/rotate |
| `SCHWAB_APP_SECRET` | Yes (1) | — | Review |

**Taxable live keys never appeared in any bak** → balance-zero taxable rotation **not** forced by this Phase-0 criterion.  
**Paper Alpaca keys + DB + Telegram tokens matched current values in 0664 baks** → treat as **exposed until rotated**.

## 6. Explicit non-actions

- No Bitwarden migration  
- No modal changes beyond server-side bak kill  
- No key rotation performed this phase (operator-owned at broker/DB)  
- `nyc-dof-auction/.env` left alone (other project, small)  
- Worktree **symlinks** to live `.env` left intact  

## See also

- `docs/_findings/bitwarden_env_posture_recon_2026-07-21.md`
